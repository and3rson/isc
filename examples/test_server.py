#!/usr/bin/env python3.6

from isc.server import Node, expose, on
from time import sleep


class TestService(object):
    name = 'test'

    @expose
    def add(self, a, b):
        return a + b

    @expose
    def raise_error(self):
        raise Exception('testing')

    def private_method(self):
        return 'Cannot call me!'

    @on('boom')
    def do_stuff(self, arg):
        print('Got stuff:', arg)

    @expose
    def slow_method(self):
        sleep(3)


service = TestService()
node = Node()
node.register_service(service)

if __name__ == '__main__':
    node.run()
