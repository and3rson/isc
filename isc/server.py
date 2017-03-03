import pika
import pickle
import traceback
import sys
from threading import Event

from isc import log

from gevent import sleep
from gevent import monkey, spawn, spawn_later
monkey.patch_all()


class Node(object):
    """
    Registers services & listens to AMQP for RPC calls & notifications.
    """

    def __init__(self):
        self.services = {}
        self.listeners = {}
        self._is_ready = Event()
        self.params = pika.ConnectionParameters('localhost')
        self._is_running = False
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
                self.channel = self.conn.channel()

                self._create_service_queues(self.channel, self.services)
                self._register_listeners(self.services)
                self._create_fanout_exchange(self.channel)
                self._schedule_methods(self.services)

                log.info('Ready')
                self._is_ready.set()
                self.channel.start_consuming()
                self._is_running = False
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

    def add_hook(self, name):
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

    def _run_scheduled_with_local_timer(self, fn, timeout):
        fn_name = fn.__name__
        exception, _ = self._call_service_method(fn_name, fn, (), {})
        if not exception:
            log.debug('Scheduled function %s completed successfully.', fn_name)
        self._schedule_with_local_timer(fn, timeout)

    def _schedule_with_local_timer(self, fn, timeout):
        spawn_later(timeout, self._run_scheduled_with_local_timer, fn, timeout)

    def _create_service_queues(self, channel, services):
        """
        Creates necessary AMQP queues, one per service.
        """
        channel.exchange_declare(exchange='isc')
        for service in services.values():
            queue = 'isc_service_{}'.format(service.name)
            channel.queue_declare(queue=queue)
            channel.queue_bind(queue, 'isc')
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
        channel.exchange_declare(exchange='isc_fanout', type='fanout')
        fanout_queue = channel.queue_declare(exclusive=True)
        channel.queue_bind(exchange='isc_fanout', queue=fanout_queue.method.queue)

        channel.basic_consume(self._on_broadcast, queue=fanout_queue.method.queue, no_ack=True)

    def _schedule_methods(self, services):
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
        service_name = method.routing_key[12:]

        if service_name not in self.services:  # pragma: no cover
            return

        channel.basic_ack(delivery_tag=method.delivery_tag)

        service = self.services[service_name]
        result = self._call_service(service, body)

        channel.basic_publish(exchange='isc', routing_key=properties.reply_to, properties=pika.BasicProperties(
            correlation_id=properties.correlation_id
        ), body=pickle.dumps(result))

    def _call_service(self, service, body):
        """
        Calls method and returns the tuple with `Exception` instance
        # or `None` and result or `None`.
        """
        try:
            fn_name, args, kwargs = pickle.loads(body)
            fn = self._get_method(service, fn_name)
        except Exception as e:
            return (str(e), None)
        else:
            return self._call_service_method(fn_name, fn, args, kwargs)

    def _call_service_method(self, fn_name, fn, args, kwargs):
        try:
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
        tb = sys.exc_info()[2]
        frame = traceback.extract_tb(tb)[-1]
        if isinstance(frame, tuple):  # pragma: no cover
            filename, lineno, _, line = frame
        else:  # pragma: no cover
            filename, lineno, line = frame.filename, frame.lineno, frame.line
        log.error('Error in RPC method "{}", file {}:{}:\n    {}\n{}: {}'.format(fn_name, filename, lineno, line, e.__class__.__name__, str(e)))

    def _get_method(self, service, fn_name):
        """
        Checks if requested method exists and can be called.
        """
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
        # TODO: Handle decoding errors
        event, data = pickle.loads(body)

        listeners = self.listeners.get(event, [])
        for fn in listeners:
            spawn(fn, data)

    def _fire_hook(self, name, *args, **kwargs):
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
    def wrapper(fn):
        if getattr(fn, '__timeouts__', None) is None:
            fn.__timeouts__ = set()
        fn.__timeouts__ |= set([timeout])
        return fn
    return wrapper
