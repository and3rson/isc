# ISC

Inter-service communication layer for Python.

Uses `AMQP` as broker and `gevent` for multiprocessing.

# Dependencies

- `gevent`
- `pika`

# Installation

```
pip install isclib
```

# Example

## Server

`test_server.py`

```python
#!/usr/bin/env python3.6

from isc.server import Node, expose, on


class TestService(object):
    name = 'test'

    @expose
    def foo(self):
        return 'bar'

    @expose
    def raise_error(self):
        raise Exception('some error')

    def private_method(self):
        return 'Cannot call me!'

    @on('boom')
    def do_stuff(self, data):
        print(data['place'], 'exploded')


service = TestService()
node = Node()
node.register_service(service)

if __name__ == '__main__':
    node.run()
```

## Client

`test_client.py`

```python
#!/usr/bin/env python3.6

from isc.client import Client, RemoteException

# `Client` is thread-safe, no need to perform any connection pooling.
client = Client()

# Call single method
assert client.invoke('test', 'foo') == 'bar'

# Handler errors
try:
    client.invoke('test', 'raise_error')
except RemoteException as e:
    # Thrown if any exception happens on the remote end.
    assert str(e) == 'some error'

# Send a broadcast
client.notify('boom', dict(place='old_building'))
```

# Contribution

Created by Andrew Dunai. Inspired by Nameko.
