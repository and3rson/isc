from unittest import TestCase
try:  # pragma: no cover
    from unittest import mock
except ImportError:  # pragma: no cover
    import mock
from time import sleep
from gevent import spawn
from gevent.event import Event
from time import time
from .server import Node, expose, on, local_timer, log
from .client import Client, RemoteException, TimeoutException, FutureResult
from .codecs import JSONCodec
from threading import Thread


class ExampleService(object):
    name = 'example'

    def __init__(self):
        # Just for the tests, don't do this - services *must* be stateless!
        self.stuff_done_event = Event()
        self.collect_stats_done = Event()

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
        sleep(2)
        return 42

    @local_timer(timeout=1)
    def collect_stats(self):
        self.collect_stats_done.set()


class GenericTest(TestCase):
    def setUp(self):
        self.node = Node(exchange='isc-unittest')
        self.service = ExampleService()
        self.node.register_service(self.service)
        self.node_greenlet = spawn(self.node.run)
        self.node.wait_for_ready()
        self.client = Client(exchange='isc-unittest')
        self.client.connect()
        self.clients = []

    def tearDown(self):
        self.client.stop()
        self.node.stop()
        self.node_greenlet.join()
        for client in self.clients:
            client.stop()

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

    def test_reconnect_and_redeliver(self):
        class SomeClient(Thread):
            def __init__(self, client):
                super(SomeClient, self).__init__()
                self.client = client
                self.future_result = None
                self.sent = Event()

            def run(self):
                self.future_result = self.client.example.add.call_async(2, 3)
                self.sent.set()

        client = Client('666.666.666.666', exchange='isc-unittest')
        self.clients.append(client)

        client_thread = SomeClient(client)
        client_thread.start()

        client.connect(wait_for_ready=False)
        sleep(2)
        self.assertFalse(client.connection._is_ready.is_set())
        sleep(2)

        self.assertFalse(client.connection._is_ready.is_set())
        client.connection.host = '127.0.0.1'
        self.assertTrue(client.connection._wait_for_ready(5))
        self.assertTrue(client_thread.sent.wait(5))
        self.assertTrue(client_thread.future_result.wait(5))
        self.assertEqual(client_thread.future_result.value, 5)

    def test_success_hooks(self):
        self.pre_call_called = False
        self.post_success_called = False
        self.post_error_called = False

        @self.node.add_hook('pre_call')
        def pre_call(*args):
            self.pre_call_called = True

        @self.node.add_hook('post_success')
        def post_success(*args):
            self.post_success_called = True

        @self.node.add_hook('post_error')
        def post_error(*args):
            self.post_error_called = True

        self.assertEqual(self.client.example.add(2, 3), 5)
        self.assertTrue(self.pre_call_called)
        self.assertTrue(self.post_success_called)
        self.assertFalse(self.post_error_called)

        self.pre_call_called = False
        self.post_success_called = False
        self.post_error_called = False

        self.assertRaises(RemoteException, self.client.example.add, (2, '3'))
        self.assertTrue(self.pre_call_called)
        self.assertFalse(self.post_success_called)
        self.assertTrue(self.post_error_called)

    def test_local_timer_timings(self):
        # Measure time taken by timer to execute.

        self.service.collect_stats_done.wait(timeout=5)

        timediffs = []
        samples = 5

        for i in range(samples):
            self.service.collect_stats_done.clear()
            start = time()
            self.service.collect_stats_done.wait()
            timediffs.append(time() - start)

        timediff_avg = sum(timediffs) / samples

        self.assertAlmostEqual(timediff_avg, 1, 1)

    def test_bad_message_payload(self):
        e = Event()
        with mock.patch.object(self.client.connection.codec, 'encode', return_value='crap'):
            with mock.patch.object(log, 'error', side_effect=lambda *args: e.set()) as error:
                self.client.example.add.call_async(2, 3)
                self.assertTrue(e.wait(1), 'log.error was not called')
                self.assertTrue(error.call_args[0][0].startswith('Failed to decode message'))

        self.assertEquals(self.client.example.add(2, 3), 5, 'Should operate normally after error')

    def test_bad_notify_payload(self):
        e = Event()
        with mock.patch.object(self.client.connection.codec, 'encode', return_value='crap'):
            with mock.patch.object(log, 'error', side_effect=lambda *args: e.set()) as error:
                self.client.notify('boom', dict(place='some_place'))
                self.assertTrue(e.wait(1), 'log.error was not called')
                self.assertTrue(error.call_args[0][0].startswith('Failed to decode message'))

        self.client.notify('boom', dict(place='some_place'))
        self.assertEqual(self.service.stuff_done_event.wait(3), True, 'Should operate normally after error')

    def test_unknown_codec(self):
        e = Event()
        ct_ = self.client.connection.codec.content_type
        self.client.connection.codec.content_type = 'random_salad'
        with mock.patch.object(log, 'error', side_effect=lambda *args: e.set()) as error:
            self.client.example.add.call_async(2, 3)
            self.assertTrue(e.wait(1), 'log.error was not called')
            self.assertTrue(error.call_args[0][0].startswith('Unknown codec'))
        self.client.connection.codec.content_type = ct_

        self.assertEquals(self.client.example.add(2, 3), 5, 'Should operate normally after error')

    def test_slow_method(self):
        self.client.set_timeout(1)
        self.assertRaises(TimeoutException, self.client.example.slow_method)
        self.client.set_timeout(3)
        self.assertEqual(self.client.example.slow_method(), 42)

    def test_multi_codec(self):
        self.assertEqual(self.client.example.add((2,), (3,)), (2, 3), 'When using pickle codec, tuple should not be downgraded to list.')
        self.client.set_codec(JSONCodec())
        self.assertEqual(self.client.example.add((2,), (3,)), [2, 3], 'When using JSON codec, tuple should be downgraded to list.')
