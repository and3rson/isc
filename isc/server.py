import pika
import pickle
import traceback
import sys
from threading import Event

from isc import log

from gevent import sleep
from gevent import monkey, spawn
monkey.patch_all()


class Node(object):
    def __init__(self):
        self.services = {}
        self.listeners = {}
        self._is_ready = Event()
        self.params = pika.ConnectionParameters('localhost')

    def on_message(self, channel, method, properties, body):
        spawn(self.validate_message, channel, method, properties, body)

    def validate_message(self, channel, method, properties, body):
        service_name = method.routing_key[12:]

        if service_name not in self.services:  # pragma: no cover
            return

        channel.basic_ack(delivery_tag=method.delivery_tag)

        service = self.services[service_name]
        result = self.call_service(service, body)

        channel.basic_publish(exchange='', routing_key=properties.reply_to, properties=pika.BasicProperties(
            correlation_id=properties.correlation_id
        ), body=pickle.dumps(result))

    def call_service(self, service, body):
        try:
            fn_name, args, kwargs = pickle.loads(body)
            fn = getattr(service, fn_name, None)

            if fn is None:
                log.warning('No method %s', fn_name)
                raise Exception('Could not find method {}.'.format(fn_name))

            if getattr(fn, '__exposed__', None) is None:
                log.warning('Method %s is not exposed', fn_name)
                raise Exception('You are not allowed to call unexposed method {}.'.format(fn_name))
        except Exception as e:
            return (str(e), None)
        else:
            try:
                result = (None, fn(*args, **kwargs))
                log.debug('{}(*{}, **{})'.format(fn_name, args, kwargs))
                return result
            except Exception as e:
                tb = sys.exc_info()[2]
                frame = traceback.extract_tb(tb)[-1]
                if isinstance(frame, tuple):  # pragma: no cover
                    filename, lineno, _, line = frame
                else:  # pragma: no cover
                    filename, lineno, line = frame.filename, frame.lineno, frame.line
                log.error('Error in RPC method "{}", file {}:{}:\n    {}\n{}: {}'.format(fn_name, filename, lineno, line, e.__class__.__name__, str(e)))
                return (str(e), None)

    def on_broadcast(self, channel, method, properties, body):
        # TODO: Handle decoding errors
        event, data = pickle.loads(body)

        listeners = self.listeners.get(event, [])
        for fn in listeners:
            spawn(fn, data)

    def register_service(self, service):
        if service.name in self.services:
            raise Exception('Service {} is already registered.'.format(service.name))
        self.services[service.name] = service

    def run(self):
        while True:
            try:
                conn = pika.BlockingConnection(self.params)
                self.conn = conn
                #     conn = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
                # except Exception as e:
                #     print(str(e))
                #     print('RabbitMQ not running? Retrying connection in 1 second.')
                #     sleep(1)
                #     continue

                channel = conn.channel()
                for service in self.services.values():
                    queue = 'isc_service_{}'.format(service.name)
                    channel.queue_declare(queue=queue)
                    channel.basic_consume(self.on_message, queue=queue, no_ack=False)

                    for attr in [getattr(service, attr, None) for attr in dir(service)]:
                        events = getattr(attr, '__on__', None)
                        if events:
                            for event in events:
                                if event not in self.listeners:
                                    self.listeners[event] = []
                                self.listeners[event].append(attr)

                channel.exchange_declare(exchange='isc_fanout', type='fanout')
                fanout_queue = channel.queue_declare(exclusive=True)
                channel.queue_bind(exchange='isc_fanout', queue=fanout_queue.method.queue)

                channel.basic_consume(self.on_broadcast, queue=fanout_queue.method.queue, no_ack=True)
                log.info('Ready')
                self.channel = channel
                self._is_ready.set()
                channel.start_consuming()
                break
            except pika.exceptions.ConnectionClosed:  # pragma: no cover
                self._is_ready.clear()
                log.error('Connection closed, retrying in 3 seconds')
                sleep(3)
                continue

    def wait_for_ready(self):
        self._is_ready.wait()

    def stop(self):
        self.conn.add_timeout(0, lambda: self.channel.stop_consuming())


def expose(fn):
    fn.__exposed__ = True
    return fn


def on(event):
    def wrapper(fn):
        if getattr(fn, '__on__', None) is None:
            fn.__on__ = set()
        fn.__on__ |= set([event])
        return fn
    return wrapper
