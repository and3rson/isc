# ISC

Inter-service communication layer for Python.

Uses `AMQP` as broker. Compatible with gevent.

[![Coverage Status](https://coveralls.io/repos/github/and3rson/isc/badge.svg)](https://coveralls.io/github/and3rson/isc) [![Build Status](https://travis-ci.org/and3rson/isc.svg)](https://travis-ci.org/and3rson/isc) [![Documentation Status](https://readthedocs.org/projects/isc/badge/?version=latest)](http://isc.readthedocs.io/en/latest/?badge=latest)

# Dependencies

- `pika`
- `kombu`

# Documentation

The docs are available via [ReadTheDocs](http://isc.readthedocs.io/en/latest/).

# Installation

```bash
pip install isclib
```

# All-in-one example

## Server

`test_server.py`

```python
#!/usr/bin/env python3.6

from isc.server import Node, expose, on, local_timer


class ExampleService(object):
    name = 'example'

    @expose
    def foo(self):
        return 'bar'

    @expose
    def dangerous_operation(self):
        raise Exception('BOOM')

    def private_method(self):
        print('Cannot call me!')

    @on('boom')
    def do_stuff(self, data):
        print(data['place'], 'exploded')

    @local_timer(timeout=5)
    def print_statistics(self):
        # Will be called every 5 seconds.
        print('Staying alive!')


service = ExampleService()
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
assert client.example.foo()  # returns 'bar'

# Raises RemoteException
client.example.dangerous_operation()

# Send a broadcast
client.notify('boom', dict(place='old_building'))

# Raises RemoteException
client.private_method()
```

# Contribution

Created by Andrew Dunai. Inspired by Nameko.
