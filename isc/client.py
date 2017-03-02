from gevent import monkey, spawn
monkey.patch_all()

import pika
import pickle
import uuid
from threading import Event

from isc import log


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
    Encapsulates future result. Provides interface to wait for future data.
    """
    def __init__(self):
        self.event = Event()
        self.result = None

    def wait(self, timeout=5):
        """
        Blocks until data is ready.
        """
        self.event.wait(timeout=float(timeout))
        return self.result

    def happen(self, result):
        """
        Fulfills the result and sets "ready" event.
        """
        self.result = result
        self.event.set()


class Connection(object):
    """
    Represents a single low-level connection to the ISC messaging broker.
    """
    def __init__(self, host):
        self.host = host
        self.future_results = {}

    def connect(self):
        """
        Connect to broker and create a callback queue with "exclusive" flag.
        """
        try:
            self.conn = pika.BlockingConnection(pika.ConnectionParameters(self.host))
        except:
            log.error('RabbitMQ not running?')
            return False

        self.channel = self.conn.channel()
        # self.channel.queue_declare(queue='test')

        self.callback_queue = self.channel.queue_declare(exclusive=True).method.queue

        self.channel.basic_consume(self.on_response, no_ack=True, queue=self.callback_queue)

        return True

    def start_consuming(self):
        """
        Start consuming messages.
        This function is blocking.
        """
        self.channel.start_consuming()

    def stop_consuming(self):
        self.channel.stop_consuming()

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
            exception, result = pickle.loads(body)
            if exception:
                exception = RemoteException(exception)
        except Exception as e:  # pragma: no cover
            exception, result = LocalException(str(e)), None
        future_result.happen((exception, result))

    def call(self, service, method, *args, **kwargs):
        """
        Serialize & publish method call request.
        """
        corr_id = str(uuid.uuid4())

        future_result = FutureResult()
        self.future_results[corr_id] = future_result

        self.channel.basic_publish(
            exchange='', routing_key='isc_service_{}'.format(service), body=pickle.dumps((method, args, kwargs)),
            properties=pika.BasicProperties(
                reply_to=self.callback_queue, correlation_id=corr_id
            )
        )

        return future_result

    def notify(self, event, data):
        """
        Serialize & publish notification.
        """
        corr_id = str(uuid.uuid4())

        self.channel.basic_publish(
            exchange='isc_fanout', routing_key='', body=pickle.dumps((event, data)),
            properties=pika.BasicProperties(
                correlation_id=corr_id
            )
        )


class ServiceProxy(object):
    def __init__(self, client, service_name):
        self.client = client
        self.service_name = service_name

    def __getattr__(self, attr):
        return MethodProxy(self.client, self.service_name, attr)


class MethodProxy(object):
    def __init__(self, client, service_name, method_name):
        self.client = client
        self.service_name = service_name
        self.method_name = method_name

    def __call__(self, *args, **kwargs):
        return self.client.invoke(self.service_name, self.method_name, *args, **kwargs)


class Client(object):
    """
    Provides simple interface to the Connection.
    """
    def __init__(self, hostname='127.0.0.1', timeout=5):
        self.connection = Connection(hostname)
        self.timeout = timeout

    def connect(self):
        if not self.connection.connect():
            return False

        spawn(self.connection.start_consuming)

    def stop(self):
        self.connection.stop_consuming()

    def set_timeout(self, timeout):
        self.timeout = timeout

    def invoke(self, service, method, *args, **kwargs):
        """
        Call a remote method.
        """

        future_result = self.connection.call(service, method, *args, **kwargs)

        data = future_result.wait(self.timeout)

        if data:
            exception, result = data
        else:
            exception, result = TimeoutException('Method {}.{} timed out.'.format(service, method)), None

        if exception:
            raise exception
        else:
            return result

    def notify(self, event, data):
        """
        Publish a notification.
        """
        self.connection.notify(event, data)

    def __getattr__(self, attr):
        return ServiceProxy(self, attr)
