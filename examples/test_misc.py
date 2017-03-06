#!/usr/bin/env python3.6

from isc.client import Client, RemoteException, TimeoutException

client = Client()
client.connect()

client.notify('boom', dict(foo='bar'))

assert client.example.add(2, 3) == 5
assert client.invoke('example', 'add', 2, 3) == 5

try:
    client.example.add(2, '3')
except RemoteException:
    pass
else:
    assert False

try:
    client.example.raise_error()
except RemoteException:
    pass
else:
    assert False

try:
    client.example.private_method()
except RemoteException:
    pass
else:
    assert False

try:
    client.example.unexisting_method()
except RemoteException:
    pass
else:
    assert False


try:
    client.set_timeout(1)
    client.example.slow_method()
except TimeoutException:
    pass
else:
    assert False

client.stop()
