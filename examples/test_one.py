#!/usr/bin/env python3.6

from isc.client import Client
import time

client = Client(exchange='isctest')
client.connect()

print('Wait 2 seconds...')
time.sleep(2)

assert client.example.add(2, 3) == 5

print('Got correct result 2, waiting 2 more seconds...')

time.sleep(2)

assert client.example.add(2, 3) == 5

print('Got correct result 2')

client.stop()
