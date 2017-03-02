#!/usr/bin/env python3.6

from isc.client import Client, RemoteException, TimeoutException

client = Client()
client.connect()

client.notify('boom', dict(foo='bar'))

assert client.test.add(2, 3) == 5
assert client.invoke('test', 'add', 2, 3) == 5

try:
    client.test.add(2, '3')
except RemoteException:
    pass
else:
    assert False

try:
    client.invoke('test', 'raise_error')
except RemoteException:
    pass
else:
    assert False

try:
    client.invoke('test', 'private_method')
except RemoteException:
    pass
else:
    assert False

try:
    client.invoke('test', 'unexisting_method')
except RemoteException:
    pass
else:
    assert False


try:
    client.set_timeout(1)
    client.invoke('test', 'slow_method')
except TimeoutException:
    pass
else:
    assert False
