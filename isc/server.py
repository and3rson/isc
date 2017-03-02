import pika
import pickle

from gevent import monkey, spawn
monkey.patch_all()


class Node(object):
    def __init__(self):
        self.services = {}
        self.listeners = {}

    def on_message(self, channel, method, properties, body):
        spawn(self.validate_message, channel, method, properties, body)

    def validate_message(self, channel, method, properties, body):
        service_name = method.routing_key[12:]

        if service_name not in self.services:
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
                print('No method', fn_name)
                raise Exception('Could not find method {}.'.format(fn_name))

            if getattr(fn, '__exposed__', None) is None:
                print('Method', fn_name, 'is not exposed')
                raise Exception('You are not allowed to call unexposed method {}.'.format(fn_name))
        except Exception as e:
            return (str(e), None)
        else:
            try:
                result = (None, fn(*args, **kwargs))
                print('{}(*{}, **{})'.format(fn_name, args, kwargs))
                return result
            except Exception as e:
                print('Error in {}: {}'.format(fn_name, str(e)))
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
        try:
            conn = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
        except:
            print('RabbitMQ not running?')
            return

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
        channel.start_consuming()


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
