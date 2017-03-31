import kombu
import uuid
import socket
from traceback import format_exc
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
    def __init__(self, cannonical_name):
        self.event = Event()
        self.exception = None
        self.value = None
        self.cannonical_name = cannonical_name

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

    # def reset(self):  # pragma: no cover
    #     self.event.clear()
    #     self.exception = None
    #     self.value = None

    def is_ready(self):
        """
        Checks if this result has been resolved or rejected.
        """
        return self.event.is_set()


class ConsumerThread(Thread):
    def __init__(self, client):
        self.client = proxy(client)
        super(ConsumerThread, self).__init__()
        self.daemon = True

    def run(self):
        while True:
            try:
                log.info('Connecting to AMQP...')
                self.client._connect()
                self.client._is_connected = True
                self.client.on_connect.fire()
                log.info('Connected to AMQP')
                self.client._start_consuming()
                self.client._is_connected = False
                self.client.on_disconnect.fire()
                return
            except Exception as e:
                self.client._is_connected = False
                if self.client.reconnect_timeout:
                    log.error(
                        'Disconnected from AMQP.\n'
                        'Retrying in {} seconds.\n'
                        'Error was: {}'.format(
                            self.client.reconnect_timeout,
                            # format_exc()
                            str(e)
                        )
                    )
                    self.client.on_error.fire()
                    sleep(self.client.reconnect_timeout)
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
                    self.client.on_error.fire()
                    return


class PublisherThread(Thread):
    def __init__(self, client):
        self.client = proxy(client)
        super(PublisherThread, self).__init__()
        self.daemon = True

    def run(self):
        while self.client._is_running:
            if self.client._is_connected:
                try:
                    request = self.client._out_queue.get(timeout=0.5)
                    with kombu.producers[self.client.conn].acquire(block=True) as producer:
                        if request['type'] == 'invoke':
                            log.debug('Publishing method invocation: %s', request)
                            producer.publish(
                                exchange=self.client.exchange,
                                routing_key='{}_service_{}'.format(self.client.exchange_name, request['service']),
                                body=request['codec'].encode((request['method'], request['args'], request['kwargs'])),
                                reply_to=self.client.callback_queue.name,
                                correlation_id=request['corr_id'],
                                content_type=self.client.codec.content_type,
                            )
                        else:
                            log.debug('Publishing fanout notification: %s', request)
                            producer.publish(
                                exchange='{}_fanout'.format(self.client.exchange_name),
                                routing_key='',
                                body=request['codec'].encode((request['event'], request['data'])),
                                correlation_id=request['corr_id'],
                                content_type=self.client.codec.content_type
                            )
                except Empty:
                    continue
            else:
                sleep(0.5)
                log.debug('Cannot publish, waiting for connection...')


class Client(object):
    """
    Represents a single low-level connection to the ISC messaging broker.
    Thread-safe.
    """
    def __init__(self, host='amqp://guest:guest@127.0.0.1:5672/', exchange='isc', codec=None, connect_timeout=2, reconnect_timeout=1, invoke_timeout=10):
        self.host = host
        self.exchange_name = exchange
        self.codec = None
        self.connect_timeout = connect_timeout
        self.reconnect_timeout = reconnect_timeout
        self.set_codec(codec)
        self.future_results = {}
        self._is_running = False
        self._is_connected = False
        self.conn = None
        self.exchange = None
        self.invoke_timeout = invoke_timeout

        self._out_queue = Queue()

        self.on_connect = EventHook()
        self.on_error = EventHook()
        self.on_disconnect = EventHook()

    def start(self):
        """
        Connect to broker and create a callback queue with "exclusive" flag.
        """
        self._is_running = True

        self._consumer_thread = ConsumerThread(self)
        self._consumer_thread.start()

        self._publisher_thread = PublisherThread(self)
        self._publisher_thread.start()

    def _connect(self):
        # self.conn = pika.BlockingConnection(pika.ConnectionParameters(self.host))
        self.conn = kombu.Connection(self.host, connect_timeout=self.connect_timeout)
        # self.conn.process_data_events = self._fix_pika_timeout(self.conn.process_data_events)

        self.channel = self.conn.channel()
        # self.channel.queue_declare(queue='test')

        self.exchange = kombu.Exchange(name=self.exchange_name, channel=self.channel, durable=False)

        self.callback_queue = self._create_callback_queue(self.channel, self.exchange)

        # log.info('Ready')

    # def _wait_for_ready(self, timeout=None):
    #     """
    #     Blocks until a connection is established.
    #     """
    #     return self._conn_event.wait(timeout)

    def _create_callback_queue(self, channel, exchange):
        name = 'response-{}'.format(uuid.uuid4())
        callback_queue = kombu.Queue(name=name, exchange=exchange, routing_key=name, exclusive=True, channel=self.channel)
        callback_queue.declare()
        return callback_queue
        # callback_queue = channel.queue_declare(exclusive=True).method.queue
        # channel.queue_bind(callback_queue, exchange=exchange)

        # channel.basic_consume(on_response, no_ack=True, queue=callback_queue)

        # return callback_queue

    def _start_consuming(self):
        """
        Start consuming messages.
        This function is blocking.
        """
        consumer = kombu.Consumer(self.conn, queues=[self.callback_queue], on_message=self._on_response, accept=[self.codec.content_type])
        consumer.consume()
        while self._is_running:
            try:
                self.conn.drain_events(timeout=0.5)
            except socket.timeout:
                continue

        # self.channel.start_consuming()

    def stop(self):
        """
        Stops the client and waits for its termination.
        """
        # self._is_running = False
        # if self.conn is not None:
        #     self.conn.add_timeout(0, lambda: self.channel.stop_consuming())
        # self._thread.join()
        self._is_running = False
        self._publisher_thread.join()
        self._consumer_thread.join()

    def set_codec(self, codec):
        """
        Sets a codec for this clent.
        """
        if isinstance(codec, codecs.AbstractCodec):
            self.codec = codec
        else:
            self.codec = codecs.PickleCodec()

    # def _on_response(self, channel, method, properties, body):
    def _on_response(self, message):
        """
        Called when a message is consumed.
        """
        # print('RESPONSE', message.body)
        # print('RESPONSE', message.properties.correlation_id)
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

    def invoke_async(self, service, method, *args, **kwargs):
        """
        Serialize & publish method call request.
        """
        # self._wait_for_ready()
        corr_id = str(uuid.uuid4())

        future_result = FutureResult('{}.{}'.format(service, method))
        self.future_results[corr_id] = future_result

        self._out_queue.put(dict(
            type='invoke',
            service=service,
            method=method,
            args=args,
            kwargs=kwargs,
            corr_id=corr_id,
            codec=self.codec
        ))

        return future_result

    def notify(self, event, data):
        """
        Serialize & publish notification.
        """
        # self._wait_for_ready()
        corr_id = str(uuid.uuid4())

        self._out_queue.put(dict(
            type='notify',
            event=event,
            data=data,
            corr_id=corr_id,
            codec=self.codec
        ))

    def invoke(self, service, method, *args, **kwargs):
        """
        Call a remote method and wait for a result.
        Blocks until a result is ready.
        """

        future_result = self.invoke_async(service, method, *args, **kwargs)

        future_result.wait(self.invoke_timeout)

        if future_result.exception:
            raise future_result.exception
        else:
            return future_result.value

    def set_invoke_timeout(self, timeout):
        """
        Sets timeout for waiting for results on this client.
        """
        self.invoke_timeout = timeout

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
