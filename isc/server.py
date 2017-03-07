import pika
import traceback
import sys
from threading import Event

from isc import codecs, log

from gevent import sleep
from gevent import monkey, spawn, spawn_later
monkey.patch_all()


class Node(object):
    """
    Registers services & listens to AMQP for RPC calls & notifications.
    """

    def __init__(self, hostname='127.0.0.1', exchange='isc'):
        self.exchange = exchange
        self._infix = '_service_'
        self.queue_name_offset = len(exchange) + len(self._infix)
        self.services = {}
        self.listeners = {}
        self._is_ready = Event()
        self.params = pika.ConnectionParameters(hostname)
        self._is_running = False
        self.codecs = {}
        self.register_codec(codecs.PickleCodec())
        self.register_codec(codecs.JSONCodec())
        self.hooks = {
            'pre_call': set(),
            'post_success': set(),
            'post_error': set()
        }

    def run(self):
        """
        Starts provider node.
        Blocks until `stop` is called.
        """
        self._is_running = True
        while self._is_running:
            try:
                self.conn = pika.BlockingConnection(self.params)
                self.conn.process_data_events = self._fix_pika_timeout(self.conn.process_data_events)
                self.channel = self.conn.channel()

                self._create_service_queues(self.channel, self.services)
                self._register_listeners(self.services)
                self._create_fanout_exchange(self.channel)
                self._schedule_methods(self.services)

                log.info('Ready')
                self._is_ready.set()
                self.channel.start_consuming()
                self._is_running = False
                self._is_ready.clear()
            except pika.exceptions.ConnectionClosed:  # pragma: no cover
                self._is_ready.clear()
                log.error('Connection closed, retrying in 3 seconds')
                sleep(3)
                continue
        log.info('Node terminated')

    def register_service(self, service):
        """
        Registers a service to make it callable & notifiable via RPC.
        """
        if service.name in self.services:
            raise Exception('Service {} is already registered.'.format(service.name))
        self.services[service.name] = service

    def register_codec(self, codec):
        """
        Registers a codec for this server.
        Codec must be an instance of :class:`isc.codecs.AbstractCodec` subclass.
        Doesn't remove previously registered codecs.
        """
        self.codecs[codec.content_type] = codec

    def add_hook(self, name):
        """
        Registers a hook to be executed when requested event occurs.
        Possible names are `pre_call`, `post_success` or `post_error`.
        """
        def decorator(fn):
            self.hooks[name] |= set([fn])
            return fn
        return decorator

    def wait_for_ready(self):
        """
        Blocks until the connection to AMQP is established.
        """
        self._is_ready.wait()

    def stop(self):
        """
        Stops provider node.
        """
        self.conn.add_timeout(0, lambda: self.channel.stop_consuming())

    def _fix_pika_timeout(self, process_data_events):
        """
        Fixes pika timeout (default is 5, we want it to be 1 for faster shutdown)
        """
        def process_data_events_new(time_limit=0):
            return process_data_events(time_limit=1)
        return process_data_events_new

    def _run_scheduled_with_local_timer(self, fn, timeout):
        """
        Runs the method and reschedules it to be executed again.
        """
        fn_name = fn.__name__
        exception, _ = self._call_service_method(fn, (), {})
        if not exception:
            log.debug('Scheduled function %s completed successfully.', fn_name)
        self._schedule_with_local_timer(fn, timeout)

    def _schedule_with_local_timer(self, fn, timeout):
        """
        Schedules a job to be executed after requested timeout.
        """
        spawn_later(timeout, self._run_scheduled_with_local_timer, fn, timeout)

    def _create_service_queues(self, channel, services):
        """
        Creates necessary AMQP queues, one per service.
        """
        channel.exchange_declare(exchange=self.exchange)
        for service in services.values():
            queue = '{}_service_{}'.format(self.exchange, service.name)
            channel.queue_declare(queue=queue)
            channel.queue_bind(queue, self.exchange)
            channel.basic_consume(self._on_message, queue=queue, no_ack=False)

    def _register_listeners(self, services):
        """
        Populates listeners dictionary to speed up notification handling.
        """
        for service in services.values():
            for attr in [getattr(service, attr, None) for attr in dir(service)]:
                for event in getattr(attr, '__on__', []):
                    if event not in self.listeners:
                        self.listeners[event] = []
                    self.listeners[event].append(attr)

    def _create_fanout_exchange(self, channel):
        """
        Creates a fanout queue to accept notifications.
        """
        channel.exchange_declare(exchange='{}_fanout'.format(self.exchange), type='fanout')
        fanout_queue = channel.queue_declare(exclusive=True)
        channel.queue_bind(exchange='{}_fanout'.format(self.exchange), queue=fanout_queue.method.queue)

        channel.basic_consume(self._on_broadcast, queue=fanout_queue.method.queue, no_ack=True)

    def _schedule_methods(self, services):
        """
        Spawns timers for periodic tasks.
        """
        for service in services.values():
            for attr in [getattr(service, attr, None) for attr in dir(service)]:
                for timeout in getattr(attr, '__timeouts__', []):
                    self._schedule_with_local_timer(attr, timeout)

    def _on_message(self, channel, method, properties, body):
        """
        Called when a message is received on one of the queues.
        """
        spawn(self._validate_message, channel, method, properties, body)

    def _validate_message(self, channel, method, properties, body):
        """
        Checks and acknowledges a received message if it can be handled
        by any registered service.
        """

        service_name = method.routing_key[self.queue_name_offset:]

        if service_name not in self.services:  # pragma: no cover
            return

        channel.basic_ack(delivery_tag=method.delivery_tag)

        # service = self.services[service_name]
        try:
            requested_codec, (fn_name, args, kwargs) = self._decode_message(properties, body)
        except Exception as e:
            log.error(str(e))
        else:
            result = self._call_service_method((service_name, fn_name), args, kwargs)

            channel.basic_publish(exchange=self.exchange, routing_key=properties.reply_to, properties=pika.BasicProperties(
                correlation_id=properties.correlation_id
            ), body=requested_codec.encode(result))

    def _decode_message(self, properties, body):
        """
        Decodes message body.
        Raises `Exception` on error.
        """
        content_type = properties.content_type

        try:
            codec = self.codecs[content_type]
        except Exception as e:
            raise Exception('Unknown codec: {}'.format(content_type))

        try:
            return codec, codec.decode(body)
        except Exception as e:
            raise Exception('Failed to decode message: {}'.format(str(e)))

    def _call_service_method(self, info, args, kwargs):
        """
        Calls method and returns the tuple with `Exception` instance
        or `None` and result or `None`.
        `info` can be tuple containing service name & method name
        or the actual callable method.
        """
        try:
            if isinstance(info, tuple):
                service_name, fn_name = info
                fn = self._get_method(service_name, fn_name)
            else:
                fn_name = info.__name__
                fn = info
            self._fire_hook('pre_call', fn_name, args, kwargs)
            result = (None, fn(*args, **kwargs))
            log.debug('{}(*{}, **{})'.format(fn_name, args, kwargs))
            self._fire_hook('post_success', fn_name, args, kwargs, result)
            return result
        except Exception as e:
            self._log_method_error(fn_name, e)
            self._fire_hook('post_error', fn_name, args, kwargs, e)
            return (str(e), None)

    def _log_method_error(self, fn_name, e):
        """
        Logs error with appropriate stack frame extracted.
        """
        tb = sys.exc_info()[2]
        frame = traceback.extract_tb(tb)[-1]
        if isinstance(frame, tuple):  # pragma: no cover
            filename, lineno, _, line = frame
        else:  # pragma: no cover
            filename, lineno, line = frame.filename, frame.lineno, frame.line
        log.error('Error in RPC method "{}", file {}:{}:\n    {}\n{}: {}'.format(fn_name, filename, lineno, line, e.__class__.__name__, str(e)))

    def _get_method(self, service_name, fn_name):
        """
        Checks if requested method exists and can be called.
        Raises `Exception` on error.
        """
        service = self.services[service_name]
        fn = getattr(service, fn_name, None)

        if fn is None:
            log.warning('No method %s', fn_name)
            raise Exception('Could not find method {}.'.format(fn_name))

        if getattr(fn, '__exposed__', None) is None:
            log.warning('Method %s is not exposed', fn_name)
            raise Exception('You are not allowed to call unexposed method {}.'.format(fn_name))

        return fn

    def _on_broadcast(self, channel, method, properties, body):
        """
        Called when a notification is received.
        Does not acknowledge notifications because they're
        delivered via `fanout` exchange.
        """
        try:
            requested_codec, (event, data) = self._decode_message(properties, body)
        except Exception as e:
            log.error(str(e))
        else:
            listeners = self.listeners.get(event, [])
            for fn in listeners:
                spawn(fn, data)

    def _fire_hook(self, name, *args, **kwargs):
        """
        Fires methods registered for a requested hook.
        """
        for hook in self.hooks[name]:
            hook(*args, **kwargs)


def expose(fn):
    """
    Marks a method as "exposed", i. e. available to be called via RPC.
    """
    fn.__exposed__ = True
    return fn


def on(event):
    """
    Marks a method as "event handler", i. e. reacting to notifications.
    """
    def wrapper(fn):
        if getattr(fn, '__on__', None) is None:
            fn.__on__ = set()
        fn.__on__ |= set([event])
        return fn
    return wrapper


def local_timer(timeout):
    """
    Marks a method as "periodic job" to execute it every `timeout` seconds.
    """
    def wrapper(fn):
        if getattr(fn, '__timeouts__', None) is None:
            fn.__timeouts__ = set()
        fn.__timeouts__ |= set([timeout])
        return fn
    return wrapper
