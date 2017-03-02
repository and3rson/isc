from unittest import TestCase
from time import sleep
from gevent import spawn
from gevent.event import Event
from .server import Node, expose, on
from .client import Client, RemoteException, TimeoutException, FutureResult


class ExampleService(object):
    name = 'example'

    def __init__(self):
        # Just for the tests, don't do this - services *must* be stateless!
        self.stuff_done_event = Event()

    @expose
    def add(self, a, b):
        return a + b

    @expose
    def raise_error(self):
        raise Exception('testing')

    def private_method(self):  # pragma: no cover
        return 'Cannot call me!'

    @on('boom')
    def do_stuff(self, arg):
        print('Got stuff:', arg)
        self.stuff_done_event.set()

    @expose
    def slow_method(self):  # pragma: no cover
        sleep(3)


class GenericTest(TestCase):
    def setUp(self):
        self.node = Node()
        self.service = ExampleService()
        self.node.register_service(self.service)
        self.node_greenlet = spawn(self.node.run)
        self.node.wait_for_ready()
        self.client = Client()
        self.client.connect()

    def tearDown(self):
        self.client.stop()
        self.node.stop()
        self.node_greenlet.join()

    def test_method_success(self):
        self.assertEqual(self.client.example.add(2, 3), 5)
        self.assertEqual(self.client.invoke('example', 'add', 2, 3), 5)

    def test_method_async(self):
        future_result = self.client.example.add.call_async(2, 3)
        self.assertIsInstance(future_result, FutureResult)
        future_result.wait()
        self.assertEqual(future_result.exception, None)
        self.assertEqual(future_result.value, 5)

    def test_method_exceptions(self):
        self.assertRaises(RemoteException, self.client.example.add)
        self.assertRaises(RemoteException, self.client.example.add, (2, '3'))

    def test_unexisting_method(self):
        self.assertRaises(RemoteException, self.client.example.unexisting_method)
        # self.assertRaises(RemoteException, self.client.unexisting_service.add, (2, 3))

    def test_unexisting_service(self):
        self.client.set_timeout(1)
        self.assertRaises(TimeoutException, self.client.unexisting_service.some_method)

    def test_raises_exception(self):
        self.assertRaises(RemoteException, self.client.example.raise_error)
        try:
            self.client.example.raise_error()
        except RemoteException as e:
            self.assertEqual(str(e), 'testing')

    def test_private_method(self):
        self.assertRaises(RemoteException, self.client.example.private_method)

    def test_notify(self):
        self.client.notify('boom', dict(place='some_place'))
        self.assertEqual(self.service.stuff_done_event.wait(3), True)

    def test_register_again(self):
        self.assertRaises(Exception, self.node.register_service, self.service)

    def test_connection_failed(self):
        client = Client('unexisting.hostname.it.should.not.exist.and.if.it.does.then.this.test.will.fail')
        self.assertFalse(client.connect())

    # def test_slow_method(self):
    #     # TODO: Does not pass.
    #     self.client.set_timeout(1)
    #     self.assertRaises(TimeoutException, self.client.example.slow_method)
