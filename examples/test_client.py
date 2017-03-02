#!/usr/bin/env python3.6

from isc.client import Client
from threading import Thread, Event
from time import time
from random import random


COUNT = 1000


class Process(Thread):
    def __init__(self, client):
        super(Process, self).__init__()
        self.proceed_evt = Event()
        self.client = client

    def run(self):
        self.proceed_evt.wait()
        start = time()
        client.test.add(random(), random())
        self.timediff = int((time() - start) * 1000)


client = Client()
client.connect()


print('Creating', COUNT, 'requesters')

threads = []

for i in range(0, COUNT):
    threads.append(Process(client))

print('Starting workers')

for thread in threads:
    thread.start()

print('Starting attack...')

for thread in threads:
    thread.proceed_evt.set()

start = time()

for thread in threads:
    thread.join()

timediff = int((time() - start) * 1000)

print('Done in {}ms'.format(timediff))

print('avg: {}ms, min: {}ms, max: {}ms'.format(
    sum([thread.timediff for thread in threads]) / len(threads),
    min([thread.timediff for thread in threads]),
    max([thread.timediff for thread in threads])
))
