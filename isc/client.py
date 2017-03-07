import pika
import uuid
from threading import Thread, Event
from time import sleep

from isc import codecs, log


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
    def __init__(self, cannonical_name):
        self.event = Event()
        self.exception = None
        self.value = None
        self.cannonical_name = cannonical_name

    def wait(self, timeout=5):
        """
        Blocks until data is ready.
        """
        if not self.event.wait(timeout=float(timeout)):
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


class Connection(object):
    """
    Represents a single low-level connection to the ISC messaging broker.
    Thread-safe.
    """
    def __init__(self, host, exchange, codec):
        self.host = host
        self.exchange = exchange
        self.codec = None
        self.set_codec(codec)
        self.future_results = {}
        self._thread = None
        self._is_ready = Event()
        self._is_running = False
        self.conn = None

    def connect(self):
        """
        Connect to broker and create a callback queue with "exclusive" flag.
        """
        self._thread = Thread(target=self._run)
        self._thread.start()

    def _run(self):
        self._is_running = True
        while self._is_running:
            try:
                self.conn = pika.BlockingConnection(pika.ConnectionParameters(self.host))
                self.conn.process_data_events = self._fix_pika_timeout(self.conn.process_data_events)

                self.channel = self.conn.channel()
                # self.channel.queue_declare(queue='test')

                self.callback_queue = self._create_callback_queue(self.channel, self.exchange, self.on_response)

                log.info('Ready')

                self._is_ready.set()
                self.start_consuming()
                self._is_running = False
                self._is_ready.clear()
            except Exception as e:
                self._is_ready.clear()
                log.error('Connection closed, retrying in 3 seconds. Error was: {}'.format(str(e)))
                sleep(3)
                continue
        log.info('Client stopped')

    def _wait_for_ready(self, timeout=None):
        """
        Blocks until a connection is established.
        """
        return self._is_ready.wait(timeout)

    def _fix_pika_timeout(self, process_data_events):
        def process_data_events_new(time_limit=0):
            return process_data_events(time_limit=1)
        return process_data_events_new

    def _create_callback_queue(self, channel, exchange, on_response):
        callback_queue = channel.queue_declare(exclusive=True).method.queue
        channel.queue_bind(callback_queue, exchange=exchange)

        channel.basic_consume(on_response, no_ack=True, queue=callback_queue)

        return callback_queue

    def start_consuming(self):
        """
        Start consuming messages.
        This function is blocking.
        """
        self.channel.start_consuming()

    def stop_consuming(self):
        """
        Stops the client and waits for its termination.
        """
        self._is_running = False
        if self.conn is not None:
            self.conn.add_timeout(0, lambda: self.channel.stop_consuming())
        self._thread.join()

    def set_codec(self, codec):
        """
        Sets a codec for this clent.
        """
        if isinstance(codec, codecs.AbstractCodec):
            self.codec = codec
        else:
            self.codec = codecs.PickleCodec()

    def on_response(self, channel, method, properties, body):
        """
        Called when a message is consumed.
        """
        future_result = self.future_results.get(properties.correlation_id, None)
        if not future_result:  # pragma: no cover
            # TODO: Should not happen!
            log.error('FIXME: This should not happen.')
            return
        try:
            exception, result = self.codec.decode(body)
            if exception:
                exception = RemoteException(exception)
        except Exception as e:  # pragma: no cover
            exception, result = LocalException(str(e)), None

        if exception:
            future_result.reject(exception)
        else:
            future_result.resolve(result)

    def call(self, service, method, *args, **kwargs):
        """
        Serialize & publish method call request.
        """
        self._wait_for_ready()
        corr_id = str(uuid.uuid4())

        future_result = FutureResult('{}.{}'.format(service, method))
        self.future_results[corr_id] = future_result

        self.channel.basic_publish(
            exchange=self.exchange,
            routing_key='{}_service_{}'.format(self.exchange, service),
            body=self.codec.encode((method, args, kwargs)),
            properties=pika.BasicProperties(
                reply_to=self.callback_queue,
                correlation_id=corr_id,
                content_type=self.codec.content_type
            )
        )

        return future_result

    def notify(self, event, data):
        """
        Serialize & publish notification.
        """
        self._wait_for_ready()
        corr_id = str(uuid.uuid4())

        self.channel.basic_publish(
            exchange='{}_fanout'.format(self.exchange),
            routing_key='',
            body=self.codec.encode((event, data)),
            properties=pika.BasicProperties(
                correlation_id=corr_id,
                content_type=self.codec.content_type
            )
        )


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


class Client(object):
    """
    Provides simple interface to the Connection.
    Thread-safe.
    """
    def __init__(self, hostname='127.0.0.1', timeout=10, exchange='isc', codec=None):
        self.connection = Connection(hostname, exchange, codec)
        self.timeout = timeout
        self._thread = None

    def connect(self, wait_for_ready=True):
        self.connection.connect()
        if wait_for_ready:
            self.connection._wait_for_ready()

    def stop(self):
        """
        Stops this client.
        """
        self.connection.stop_consuming()

    def set_timeout(self, timeout):
        """
        Sets timeout for waiting for results on this client.
        """
        self.timeout = timeout

    def set_codec(self, codec):
        """
        Sets codec for this client.
        """
        self.connection.set_codec(codec)

    def invoke(self, service, method, *args, **kwargs):
        """
        Call a remote method and wait for a result.
        Blocks until a result is ready.
        """

        future_result = self.invoke_async(service, method, *args, **kwargs)

        future_result.wait(self.timeout)

        if future_result.exception:
            raise future_result.exception
        else:
            return future_result.value

    def invoke_async(self, service, method, *args, **kwargs):
        """
        Calls a remote method and returns a :class:`.FutureResult`.
        Does not block.
        """
        return self.connection.call(service, method, *args, **kwargs)

    def notify(self, event, data):
        """
        Publish a notification.
        """
        self.connection.notify(event, data)

    def __getattr__(self, attr):
        """
        Convenience method.
        Returns :class:`.ServiceProxy` to make it look like we're actually calling
        local methods from local objects.
        """
        return ServiceProxy(self, attr)
