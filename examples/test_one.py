#!/usr/bin/env python3.6

from isc.client import Client

client = Client(exchange='isctest')
client.connect()

assert client.example.add(2, 3) == 5
import time; time.sleep(1)
assert client.example.add(2, 3) == 5

client.stop()
