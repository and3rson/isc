#!/usr/bin/env python3.6

from isc.server import Node, expose, on, local_timer
from time import sleep
import logging


class ExampleService(object):
    name = 'example'

    def __init__(self):
        self.tracker = None

    @expose
    def add(self, a, b, wait=0):
        sleep(wait)
        return str(a + b) * 8000

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

    @expose
    def start_tracking(self):
        self.tracker = tracker.SummaryTracker()

    @expose
    def get_summary(self):
        return list(self.tracker.format_diff())

    # @local_timer(timeout=3)
    # def print_stats(self):
    #     print('Stats: foobar')


service = ExampleService()
node = Node(exchange='isctest')
node.set_logging_level(logging.DEBUG)
node.register_service(service)

if __name__ == '__main__':
    try:
        node.run()
    except KeyboardInterrupt:
        node.stop()
