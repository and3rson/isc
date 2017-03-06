#!/usr/bin/env python3.6

from isc.client import Client
from threading import Thread, Event
from time import time
from random import random


ITERATIONS = 1
COUNT = 1000


class Process(Thread):
    def __init__(self, client):
        super(Process, self).__init__()
        self.proceed_evt = Event()
        self.client = client
        self.timediff = 0

    def run(self):
        self.proceed_evt.wait()
        for i in range(0, ITERATIONS):
            start = time()
            client.example.add(random(), random())
            self.timediff += int((time() - start) * 1000)


client = Client(exchange='isctest')
client.connect()

client.example.start_tracking()

print('Creating', COUNT, 'requesters')

threads = []

for i in range(0, COUNT):
    threads.append(Process(client))

print('Starting workers')

for thread in threads:
    thread.start()

print('Starting attack ({} requests per worker)...'.format(ITERATIONS))

for thread in threads:
    thread.proceed_evt.set()

start = time()

for thread in threads:
    thread.join()

timediff = int((time() - start) * 1000)

print('Done in {}ms'.format(timediff))

print('avg: {}ms, min: {}ms, max: {}ms'.format(
    sum([thread.timediff / ITERATIONS for thread in threads]) / len(threads),
    min([thread.timediff / ITERATIONS for thread in threads]),
    max([thread.timediff / ITERATIONS for thread in threads])
))

print('Final server summary:')
summary = client.example.get_summary()
for line in summary:
    print(line)

client.stop()
