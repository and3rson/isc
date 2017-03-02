#!/usr/bin/env python3.6

from isc.client import Client, RemoteException, TimeoutException

client = Client()

client.notify('boom', dict(foo='bar'))

assert client.invoke('test', 'foo') == 'bar'

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
    client.invoke('test', 'slow_method', timeout=1)
except TimeoutException:
    pass
else:
    assert False
