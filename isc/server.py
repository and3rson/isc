from functools import partial
# import pika
import kombu
from kombu.pools import producers
from kombu.mixins import ConsumerMixin
import traceback
import sys
import uuid
try:
    from inspect import signature
except ImportError:
    signature = None
from threading import Thread, Event, Lock
from multiprocessing.pool import ThreadPool

from isc import codecs, log

from time import sleep


class Node(ConsumerMixin):
    """
    Registers services & listens to AMQP for RPC calls & notifications.
    """

    channel_lock = Lock()

    SPECIAL_METHODS = [
        '_inspect'
    ]

    def __init__(self, hostname='127.0.0.1', url=None, exchange='isc', thread_pool_size=8):
        self.exchange = exchange
        self._infix = '_service_'
        self.queue_name_offset = len(exchange) + len(self._infix)
        self.services = {}
        self.listeners = {}
        self._is_ready = Event()
        self._is_ready.set()
        if url is None:
            self.url = 'amqp://guest:guest@{}/'.format(hostname)
        else:
            self.url = url
        self._is_running = False
        self.codecs = {}
        self.register_codec(codecs.PickleCodec())
        self.register_codec(codecs.JSONCodec())
        self.register_codec(codecs.TypedJSONCodec())
        self.hooks = {
            'pre_call': set(),
            'post_success': set(),
            'post_error': set()
        }
        self.pool = ThreadPool(thread_pool_size)
        self.connection = kombu.Connection(self.url)

    def run(self):
        self._register_listeners(self.services)
        self._schedule_methods(self.services)
        super(Node, self).run()

    def get_consumers(self, Consumer, channel):
        consumers = [
            self._create_service_queues(self.services, Consumer, channel),
            self._create_fanout_exchange(Consumer, channel)
        ]
        return consumers

    def _inspect(self, service):
        attributes = [(key, getattr(service, key)) for key in dir(service)]

        exposed = [(key, attr) for key, attr in attributes if getattr(attr, '__exposed__', None) is not None]
        exposed_dict = {
            key: str(signature(attr)) if signature else None
            for key, attr
            in exposed
        }

        listeners = [(key, attr) for key, attr in attributes if getattr(attr, '__on__', None) is not None]
        listeners_dict = {
            key: list(attr.__on__)
            for key, attr
            in listeners
        }

        return dict(
            exposed=exposed_dict,
            listeners=listeners_dict
        )

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
        self._is_running = False
        self.should_stop = True

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
        Thread(
            target=self._wait_and_run,
            args=(
                timeout,
                self._run_scheduled_with_local_timer,
                (fn, timeout),
                {}
            )
        ).start()

    def _wait_and_run(self, interval, fn, args, kwargs):
        sleep(interval)
        fn(*args, **kwargs)

    def _create_service_queues(self, services, Consumer, channel):
        """
        Creates necessary AMQP queues, one per service.
        """
        log.debug('Declaring exchange %s', self.exchange)
        exchange = kombu.Exchange(
            self.exchange,
            channel=channel,
            durable=False
        )
        exchange.declare()
        queues = []
        for service in services.values():
            queue_name = '{}_service_{}'.format(self.exchange, service.name)
            log.debug('Declaring service queue %s', queue_name)
            queue = kombu.Queue(
                channel=channel,
                name=queue_name,
                exchange=exchange,
                routing_key=queue_name,
                exclusive=False,
                durable=False,
            )
            queue.declare()
            queues.append(queue)
        consumer = Consumer(
            queues=queues,
            on_message=self._on_message,
            no_ack=False
        )
        return consumer

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

    def _create_fanout_exchange(self, Consumer, channel):
        """
        Creates a fanout queue to accept notifications.
        """
        exchange_name = '{}_fanout'.format(self.exchange)
        log.debug('Declaring fanout exchange %s', exchange_name)
        exchange = kombu.Exchange(
            name=exchange_name,
            channel=channel,
            durable=False,
            type='fanout'
        )
        exchange.declare()
        queue_name = 'fanout_callback_{}'.format(uuid.uuid4())
        log.debug('Declaring fanout queue %s', queue_name)
        queue = kombu.Queue(
            name=queue_name,
            exchange=exchange,
            exclusive=True,
            durable=False,
            channel=channel
        )
        queue.declare()
        consumer = Consumer(
            # self.connection,
            queues=[queue],
            on_message=self._on_broadcast,
            no_ack=True
            # no_ack=True
        )

        return consumer

    def _schedule_methods(self, services):
        """
        Spawns timers for periodic tasks.
        """
        for service in services.values():
            for attr in [getattr(service, attr, None) for attr in dir(service)]:
                for timeout in getattr(attr, '__timeouts__', []):
                    self._schedule_with_local_timer(attr, timeout)

    def _on_message(self, message):
        """
        Called when a message is received on one of the queues.
        """
        log.debug('Received message %s', message)
        self.pool.apply(self._validate_message, args=(message,))

    def _validate_message(self, message):
        """
        Checks and acknowledges a received message if it can be handled
        by any registered service.
        """
        try:
            service_name = message.delivery_info['routing_key'][self.queue_name_offset:]

            if service_name not in self.services:  # pragma: no cover
                return

            message.ack()

            try:
                log.debug('Got invocation ..{}'.format(
                    str(message.properties['correlation_id'])[-4:]
                ))
                requested_codec, (fn_name, args, kwargs) = self._decode_message(message)
            except Exception as e:
                log.error(str(e))
            else:
                result = self._call_service_method((service_name, fn_name), args, kwargs)

                log.debug('Publishing response for invocation ..{}'.format(
                    str(message.properties['correlation_id'])[-4:]
                ))

                # Node.channel_lock.acquire()
                try:
                    with producers[self.connection].acquire(block=True) as producer:
                        producer.publish(
                            requested_codec.encode(result),
                            exchange=self.exchange,
                            routing_key=message.properties['reply_to'],
                            correlation_id=message.properties['correlation_id']
                            # body=requested_codec.encode(result)
                        )
                except Exception as e:
                    log.error('Failed to publish message')
                    traceback.print_exc()
                # Node.channel_lock.release()
        except Exception as e:
            log.error('Unhandled exception in _validate_message.')
            traceback.print_exc()

    def _decode_message(self, message):
        """
        Decodes message body.
        Raises `Exception` on error.
        """
        content_type = message.content_type

        try:
            codec = self.codecs[content_type]
        except Exception as e:
            raise Exception('Unknown codec: {}'.format(content_type))

        try:
            return codec, codec.decode(message.body)
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

            args_str = ', '.join(map(repr, args))
            kwargs_str = ', '.join(['{}={}'.format(k, repr(v)) for k, v in kwargs.items()])

            args_kwargs_str = ', '.join((args_str, kwargs_str))

            log.debug('{}({})'.format(fn_name, args_kwargs_str))
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
        log.error(
            'Error in RPC method "{}", file {}:{}:\n    {}\n{}: {}'.format(
                fn_name, filename, lineno, line, e.__class__.__name__, str(e)
            )
        )

    def _get_method(self, service_name, fn_name):
        """
        Checks if requested method exists and can be called.
        Raises `Exception` on error.
        """
        service = self.services[service_name]

        fn = getattr(service, fn_name, None)

        if fn is None:
            if fn_name in self.__class__.SPECIAL_METHODS:
                return partial(getattr(self, fn_name), service)
            log.warning('No method %s', fn_name)
            raise Exception('Could not find method {}.'.format(fn_name))

        if getattr(fn, '__exposed__', None) is None:
            log.warning('Method %s is not exposed', fn_name)
            raise Exception('You are not allowed to call unexposed method {}.'.format(fn_name))

        return fn

    def _on_broadcast(self, message):
        """
        Called when a notification is received.
        Does not acknowledge notifications because they're
        delivered via `fanout` exchange.
        """
        try:
            try:
                requested_codec, (event, data) = self._decode_message(message)
            except Exception as e:
                log.error(str(e))
            else:
                log.debug('Got notification ..{}'.format(
                    str(message.properties['correlation_id'])[-4:]
                ))

                listeners = self.listeners.get(event, [])
                for fn in listeners:
                    self.pool.apply_async(fn, args=(data,))
        except Exception as e:
            log.error('Unhandled exception in _on_broadcast')
            traceback.print_exc()

    def _fire_hook(self, name, *args, **kwargs):
        """
        Fires methods registered for a requested hook.
        """
        for hook in self.hooks[name]:
            hook(*args, **kwargs)

    def set_logging_level(self, level):
        """
        Set logging level.
        """
        log.set_level(level)


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
