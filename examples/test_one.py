#!/usr/bin/env python3.6

from isc.client import Client, RemoteException, TimeoutException

client = Client()
client.connect()

assert client.test.add(2, 3) == 5
