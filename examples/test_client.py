#!/usr/bin/env python3.6

from isc.client import Client
from threading import Thread, Event
from time import time
from random import random
import logging


ITERATIONS = 1
CONN_POOL_SIZE = 1
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
            self.client.example.add(random(), random(), wait=0)
            self.timediff += int((time() - start) * 1000)


def create_client():
    client = Client(exchange='isctest')
    client.set_logging_level(logging.INFO)
    client.start()
    return client

"""
client = create_client()
client.example.start_tracking()
"""

print('Creating', CONN_POOL_SIZE, 'connections')

clients = []
events = []

for _ in range(CONN_POOL_SIZE):
    event = Event()
    client = create_client()
    clients.append(client)
    events.append(event)
    client.on_connect += event.set

for i, (client, event) in enumerate(zip(clients, events)):
    print('Waiting for client', i, 'to become ready')
    event.wait()
    print('Client', i, 'ready')

print('Creating', COUNT, 'requesters')

threads = []

for i in range(0, COUNT):
    threads.append(Process(clients[i % CONN_POOL_SIZE]))

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

"""
print('Final server summary:')
summary = client.example.get_summary()
for line in summary:
    print(line)
"""

for client in clients:
    client.stop()
