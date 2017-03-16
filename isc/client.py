from gevent import monkey
monkey.patch_all()

# import pika
import kombu
import uuid
import gevent
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
        self.conn = None
        self._ready = Event()

    def connect(self):
        """
        Connect to broker and create a callback queue with "exclusive" flag.
        """
        if self.conn:
            raise LocalException('Already connected')

        self._thread = gevent.spawn(self._run)
        # self._thread.start()

    def _run(self):
        self.conn = kombu.Connection(self.host)
        # self.channel = self.conn.channel()
        # self.pool = self.conn.Pool(10)
        self.callback_queue = self._create_callback_queue(self.conn, self.exchange)

        # conn = self.pool.acquire()

        self.call('example', 'add', 2, 3)

        with kombu.Consumer(
            self.conn,
            on_message=self.on_response,
            queues=[self.callback_queue],
            # accept=['pickle']
            no_ack=True
        ):
            while True:
                print('drain')
                self.conn.drain_events()
                print('drained')

    def wait_for_ready(self):
        self._ready.wait()

    def disconnect(self):
        if self.conn is None:
            raise LocalException('Not connected')
        self.conn.close()
        self.conn = None

    def _create_callback_queue(self, conn, exchange):
        # callback_queue = channel.queue_declare(exclusive=True).method.queue
        # channel.queue_bind(callback_queue, exchange=exchange)

        # channel.basic_consume(on_response, no_ack=True, queue=callback_queue)

        # return callback_queue

        callback_queue = kombu.Queue(kombu.uuid(), exclusive=True, auto_delete=True, channel=conn)
        callback_queue.declare()
        return callback_queue

    # def stop_consuming(self):
    #     """
    #     Stops the client and waits for its termination.
    #     """
    #     self._is_running = False
    #     if self.conn is not None:
    #         self.conn.add_timeout(0, lambda: self.channel.stop_consuming())
    #     self._thread.join()

    def set_codec(self, codec):
        """
        Sets a codec for this clent.
        """
        if isinstance(codec, codecs.AbstractCodec):
            self.codec = codec
        else:
            self.codec = codecs.PickleCodec()

    def on_response(self, message):
        """
        Called when a message is consumed.
        """
        print('message:', message)
        future_result = self.future_results.get(message.properties['correlation_id'], None)
        if not future_result:  # pragma: no cover
            # TODO: Should not happen!
            log.error('FIXME: This should not happen.')
            return
        try:
            exception, result = self.codec.decode(message.body)
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
        # self._wait_for_ready()
        corr_id = str(uuid.uuid4())

        future_result = FutureResult('{}.{}'.format(service, method))
        self.future_results[corr_id] = future_result

        print('pub')

        # conn = self.pool.acquire()

        print('NN', self.callback_queue.name)

        with kombu.Producer(self.conn) as producer:
            producer.publish(
                self.codec.encode((method, args, kwargs)),
                exchange=self.exchange,
                routing_key='{}_service_{}'.format(self.exchange, service),
                # declare=[self.callback_queue],
                reply_to=self.callback_queue.name,
                correlation_id=corr_id,
                headers=dict(
                    codec_content_type=self.codec.content_type
                )
            )

        # conn.release()

        print('pub done')

        # self.channel.basic_publish(
        #     exchange=self.exchange,
        #     routing_key='{}_service_{}'.format(self.exchange, service),
        #     body=self.codec.encode((method, args, kwargs)),
        #     properties=pika.BasicProperties(
        #         reply_to=self.callback_queue,
        #         correlation_id=corr_id,
        #         content_type=self.codec.content_type
        #     )
        # )

        return future_result

    def notify(self, event, data):
        """
        Serialize & publish notification.
        """
        self._wait_for_ready()
        corr_id = str(uuid.uuid4())

        with kombu.Producer(self.conn) as producer:
            producer.publish(
                self.codec.encode((event, data)),
                exchange='{}_fanout'.format(self.exchange),
                routing_key='',
                correlation_id=corr_id,
                content_type=self.codec.content_type
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
    def __init__(self, hostname='amqp://127.0.0.1', timeout=10, exchange='isc', codec=None):
        self.connection = Connection(hostname, exchange, codec)
        self.timeout = timeout

    def connect(self, wait_for_ready=True):
        """
        Start this client.
        """
        print('connecting...')
        self.connection.connect()
        # if wait_for_ready:
        #     self.connection.wait_for_ready()
        print('connected')

    def stop(self):
        """
        Stops this client.
        """
        self.connection.disconnect()

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
