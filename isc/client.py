import kombu
import uuid
import socket
from threading import Thread, Event
from six.moves.queue import Queue, Empty
from time import sleep
from weakref import proxy

from . import codecs, log
from .eventhook import EventHook


class IPCException(Exception):
    pass


class RemoteException(IPCException):
    pass


class LocalException(IPCException):
    pass


class TimeoutException(LocalException):
    pass


class FutureResult(object):
    """
    Encapsulates future result.
    Provides interface to block until future data is ready.
    Thread-safe.
    """
    def __init__(self, cannonical_name, **extra):
        self.event = Event()
        self.exception = None
        self.value = None
        self.cannonical_name = cannonical_name
        self.extra = extra

    def wait(self, timeout=5):
        """
        Blocks until data is ready.
        """
        if not self.event.wait(timeout=timeout):
            self.exception = TimeoutException()
            return False
        return True

    def resolve(self, value):
        """
        Resolves this promise with result and sets "ready" event.
        """
        if not self.is_ready():
            self.exception = None
            self.value = value
            self.event.set()

    def reject(self, exception):
        """
        Rejects this promise with exception and sets "ready" event.
        """
        if not self.is_ready():
            self.exception = exception
            self.value = None
            self.event.set()

    def is_ready(self):
        """
        Checks if this result has been resolved or rejected.
        """
        return self.event.is_set()


class QueuedRequest(object):
    """
    Internal class. Represents pending outgoing message.
    """
    def __init__(self, codec, **kwargs):
        self.codec = codec
        self.correlation_id = str(uuid.uuid4())
        self.__dict__.update(**kwargs)


class QueuedInvocation(QueuedRequest):
    """
    Internal class. Represents pending outgoing method call.
    """
    def __init__(self, codec, service, method, args, kwargs):
        super(QueuedInvocation, self).__init__(
            codec,
            service=service,
            method=method,
            args=args,
            kwargs=kwargs
        )


class QueuedNotification(QueuedRequest):
    """
    Internal class. Represents pending outgoing notification.
    """
    def __init__(self, codec, event, data):
        super(QueuedNotification, self).__init__(
            codec,
            event=event,
            data=data
        )


class ConsumerThread(Thread):
    """
    Internal class. Represents connection & message consuming thread.
    """

    def __init__(self, hostname, exchange_name, connect_timeout, reconnect_timeout, codec):
        super(ConsumerThread, self).__init__()

        self.daemon = True
        self._is_running = False
        self._is_connected = False

        self._hostname = hostname
        self._exchange_name = exchange_name

        self.on_connect = EventHook()
        self.on_error = EventHook()
        self.on_disconnect = EventHook()
        self.on_message = EventHook()

        self._connect_timeout = connect_timeout
        self._reconnect_timeout = reconnect_timeout

        if not isinstance(codec, codecs.AbstractCodec):
            codec = codecs.PickleCodec()
        self._codec = codec

    def run(self):
        self._is_running = True
        while self._is_running:
            try:
                log.info('Connecting to AMQP...')
                self._connect()
                self._is_connected = True
                self.on_connect.fire()
                log.info('Connected to AMQP')
                self._start_consuming()
                self._is_connected = False
                self.on_disconnect.fire()
                return
            except Exception as e:
                self._is_connected = False
                if self._reconnect_timeout:
                    log.error(
                        'Disconnected from AMQP.\n'
                        'Retrying in {} seconds.\n'
                        'Error was: {}'.format(
                            self._reconnect_timeout,
                            # format_exc()
                            str(e)
                        )
                    )
                    self.on_error.fire()
                    sleep(self._reconnect_timeout)
                    continue
                else:
                    log.error(
                        'Disconnected from AMQP.\n'
                        'Not reconnecting because reconnect_timeout = 0.\n'
                        'Error was: {}'.format(
                            # format_exc()
                            str(e)
                        )
                    )
                    self.on_error.fire()
                    return

    def _connect(self):
        self._conn = kombu.Connection(
            self._hostname,
            connect_timeout=self._connect_timeout
        )

        self._channel = self._conn.channel()

        self._exchange = kombu.Exchange(
            name=self._exchange_name,
            channel=self._channel,
            durable=False
        )

        self._callback_queue = self._create_callback_queue(
            self._channel,
            self._exchange
        )

    def _create_callback_queue(self, channel, exchange):
        name = 'response-{}'.format(uuid.uuid4())
        callback_queue = kombu.Queue(
            name=name,
            exchange=exchange,
            routing_key=name,
            exclusive=True,
            channel=self._channel
        )
        callback_queue.declare()
        return callback_queue

    def _start_consuming(self):
        """
        Start consuming messages.
        This function is blocking.
        """
        consumer = kombu.Consumer(
            self._conn,
            queues=[self._callback_queue],
            on_message=self._on_message,
            accept=[self._codec.content_type],
            no_ack=True
        )

        consumer.consume()

        while self._is_running:
            try:
                self._conn.drain_events(timeout=0.5)
            except socket.timeout:
                continue

    def _on_message(self, message):
        log.debug('Got response for invocation ..{}'.format(
            str(message.properties['correlation_id'])[-4:]
        ))
        self.on_message.fire(message)

    def is_connected(self):
        return self._is_connected

    def shutdown_worker(self):
        self._is_running = False

    def get_connection(self):
        return self._conn

    def get_codec(self):
        return self._codec

    def get_exchange(self):
        return self._exchange

    def get_callback_queue(self):
        return self._callback_queue


class PublisherThread(Thread):
    """
    Internal class. Represents message publishing thread.
    """

    def __init__(self, consumer):
        self.consumer = proxy(consumer)
        super(PublisherThread, self).__init__()
        self.daemon = True
        self._out_queue = Queue()
        self._is_running = False

    def run(self):
        self._is_running = True
        while self._is_running:
            if self.consumer.is_connected():
                try:
                    queued_request = self._out_queue.get(timeout=0.5)
                    with kombu.producers[self.consumer.get_connection()].acquire(block=True) as producer:
                        try:
                            self._dispatch_request(queued_request, producer)
                        except Exception as e:
                            # except ConnectionResetError:
                            log.debug('Failed to dispatch request, re-enqueueing again, error was: {}'.format(
                                str(e)
                            ))
                            self.enqueue(queued_request)
                except Empty:
                    continue
            else:
                sleep(0.5)
                log.debug('Waiting for consumer to be ready...')

    def enqueue(self, queued_request):
        self._out_queue.put(queued_request)

    def _dispatch_request(self, queued_request, producer):
        if isinstance(queued_request, QueuedInvocation):
            log.debug('Publishing invocation ..{}'.format(
                queued_request.correlation_id[-4:]
            ))
            producer.publish(
                exchange=self.consumer.get_exchange(),
                routing_key='{}_service_{}'.format(
                    self.consumer.get_exchange().name,
                    queued_request.service
                ),
                body=queued_request.codec.encode((
                    queued_request.method,
                    queued_request.args,
                    queued_request.kwargs
                )),
                reply_to=self.consumer.get_callback_queue().name,
                correlation_id=queued_request.correlation_id,
                content_type=self.consumer.get_codec().content_type,
            )
        else:
            log.debug('Publishing notification ..{}'.format(
                queued_request.correlation_id[-4:]
            ))
            producer.publish(
                exchange='{}_fanout'.format(
                    self.consumer.get_exchange().name
                ),
                routing_key='',
                body=queued_request.codec.encode((
                    queued_request.event,
                    queued_request.data
                )),
                correlation_id=queued_request.correlation_id,
                content_type=self.consumer.get_codec().content_type
            )

    def shutdown_worker(self):
        self._is_running = False


class Client(object):
    """
    Represents a single low-level connection to the ISC messaging broker.
    Thread-safe.
    """
    def __init__(self, host='amqp://guest:guest@127.0.0.1:5672/', exchange='isc', codec=None, connect_timeout=2, reconnect_timeout=3, invoke_timeout=20):
        self.future_results = {}

        self._invoke_timeout = invoke_timeout

        self._consumer = ConsumerThread(host, exchange, connect_timeout, reconnect_timeout, codec)
        self._publisher = PublisherThread(self._consumer)

        self._consumer.on_message += self._on_response

        self.on_connect = self._consumer.on_connect
        self.on_error = self._consumer.on_error
        self.on_disconnect = self._consumer.on_disconnect

    def start(self):
        """
        Start connection & publisher threads.
        """
        self._consumer.start()
        self._publisher.start()

    def stop(self):
        """
        Stops the client and waits for its termination.
        """
        self._publisher.shutdown_worker()
        self._consumer.shutdown_worker()
        self._publisher.join()
        self._consumer.join()

    def _on_response(self, message):
        """
        Called when a message is consumed.
        """
        future_result = self.future_results.get(message.properties['correlation_id'], None)
        if not future_result:  # pragma: no cover
            # TODO: Should not happen!
            log.error('FIXME: This should not happen.')
            return
        try:
            exception, result = self._consumer.get_codec().decode(message.body)
            if exception:
                exception = RemoteException(exception)
        except Exception as e:  # pragma: no cover
            exception, result = LocalException(str(e)), None

        if exception:
            future_result.reject(exception)
        else:
            future_result.resolve(result)

    def invoke_async(self, service, method, *args, **kwargs):
        """
        Serialize & publish method call request.
        """
        queued_request = QueuedInvocation(self._consumer.get_codec(), service, method, args, kwargs)

        future_result = FutureResult('{}.{}'.format(service, method))
        self.future_results[queued_request.correlation_id] = future_result

        self._publisher.enqueue(queued_request)

        return future_result

    def notify(self, event, data):
        """
        Serialize & publish notification.
        """
        queued_request = QueuedNotification(self._consumer.get_codec(), event, data)

        self._publisher.enqueue(queued_request)

    def invoke(self, service, method, *args, **kwargs):
        """
        Call a remote method and wait for a result.
        Blocks until a result is ready.
        """
        future_result = self.invoke_async(service, method, *args, **kwargs)

        future_result.wait(self._invoke_timeout)

        if future_result.exception:
            raise future_result.exception
        else:
            return future_result.value

    def set_invoke_timeout(self, timeout):
        """
        Sets timeout for waiting for results on this client.
        """
        self._invoke_timeout = timeout

    def __getattr__(self, attr):
        """
        Convenience method.
        Returns :class:`.ServiceProxy` to make it look like we're actually calling
        local methods from local objects.
        """
        return ServiceProxy(self, attr)


class ServiceProxy(object):
    """
    Convenience wrapper for service.

    It allows you to perform attribute chaining (e. g. :code:`client.example.add(2, 3)`)
    """
    def __init__(self, client, service_name):
        self.client = client
        self.service_name = service_name

    def __getattr__(self, attr):
        """
        Returns :class:`.MethodProxy`
        """
        return MethodProxy(self.client, self.service_name, attr)


class MethodProxy(object):
    """
    Convenience wrapper for method.

    It allows you to perform attribute chaining (e. g. :code:`client.example.add(2, 3)`)
    """
    def __init__(self, client, service_name, method_name):
        self.client = client
        self.service_name = service_name
        self.method_name = method_name

    def __call__(self, *args, **kwargs):
        """
        Finalizes the chain & performs actual RPC invocation.
        Blocks while waiting for result.

        Returns the result.

        This is same as calling :func:`~isc.client.Client.invoke`
        """
        return self.client.invoke(self.service_name, self.method_name, *args, **kwargs)

    def call_async(self, *args, **kwargs):
        """
        Finalizes the chain & performs actual RPC invocation.
        Does not block.

        Returns :class:`.FutureResult`.

        This is same as calling :func:`~isc.client.Client.invoke_async`
        """
        return self.client.invoke_async(self.service_name, self.method_name, *args, **kwargs)
