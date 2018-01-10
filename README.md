# What is an ISC?

ISC is *RPC on steroids.*

This is a framework for Python designed to build distributed applications. It is designed to play well with Django and helps you to quickly build architectures from scratch.

ISC stands for Inter-Service Communication. It is **the library you missed to write scalable distributed systems using microservices pattern in Django.**

It uses RabbitMQ as messaging broker and is compatible with gevent monkey patching.

[![Coverage Status](https://coveralls.io/repos/github/and3rson/isc/badge.svg?1)](https://coveralls.io/github/and3rson/isc) [![Build Status](https://travis-ci.org/and3rson/isc.svg)](https://travis-ci.org/and3rson/isc) [![Documentation Status](https://readthedocs.org/projects/isc/badge/?version=latest)](http://isc.readthedocs.io/en/latest/?badge=latest)

# Django + ISC = ♥

ISC supports Django and makes it easy and intuitive to build a distributed system using. We're trying to make you capable of walking away from the monolythic architecture of typical Django apps.

# The philosophy

- **Distribution.** Service is an application (Python, Django, Flask or whatever) that performs a set of tasks, and performs them well.
- **Encapsulation.** If service needs to perform the work that the other service is responsible for, it should ask the other service to do so.
- **Abstraction.** All services are clients, irregardlessly of whether they provide functions or perform RPC calls to other services. Service doesn't need to know the address or specifications of each other. Services can also broadcast messages to multiple other services.

# Psst: You can also write some of your [services in NodeJS](https://www.npmjs.com/package/isclib)!

And of course they can communicate with your Django apps because they share the same protocol. How cool is that?

# How does it work?

1. You declare some services which are basically just classes with exposed methods.
2. *[Not required for Django]* You instantiate & register your services.
3. You run the worker that handles incoming requests and delivers function return values back to the caller (Classic RPC pattern.) For Django this is achieved by running `./manage.py isc`.
4. [Django only] Apart from having the `isc` running, you'll now want to also start your web server with `./manage.py runserver` in a different terminal. Now you have 2 processes running: 1 for Django itself and 1 for ISC worker that will perform tasks asynchronously. Because `isc` is a Django management command, you can easily use all of Django's fascilities in your ISC services: ORM, templating etc. You can even send RPC calls from one services to the others.

# Dependencies

- `pika`
- `kombu`
- A running `rabbitmq` server.

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
client.example.foo()  # returns 'bar'

# Raises RemoteException
client.example.dangerous_operation()

# Send a broadcast
client.notify('boom', dict(place='old_building'))

# Raises RemoteException
client.private_method()

# Do not wait for result
future = client.example.foo.call_async()
# ...or if you want, you can manually wait for it:
future.wait()
print(future.value)
```

# Playing with Django

Using ISC with Django is very simple.

In order to integrate ISC into your Django app, you need to perform those steps:

1. Classically, add `isc` to `INSTALLED_APPS`.

2. Add configuration for your services into your `settings.py`:

```python
ISC = {
    # Specify where your RabbitMQ lives.
    'url': os.getenv('RABBITMQ_URL', 'amqp://guest:guest@127.0.0.1:5672/'),

    # Enumerate your service classes here
    'services': [
        'myapp.services.ExampleService',
        'myapp.services.UserService',
        'myapp.services.ChatService',
    ],

    # Hooks are methods that are evaluated when an RPC request is handler.
    # 'hooks': {
    #     'post_success': 'myapp.utils.handle_success'
    #     'post_error': 'myapp.utils.handle_error',
    # },
    # Size of worker thread pool for server
    # 'thread_pool_size': 8
}
```

3. Start the worker that handles incoming requests to your services by running `./manage.py isc` and that's it!

4. In order to test calling some ISC methods from the services you've just defined run `./manage.py iscshell`:

```python
$ ./manage.py iscshell
>>> print(rpc.example.foo())
bar
```

5. You can now write other applications that retrieve data from your app via ISC. They can also host their own services.

# Supported Python versions

ISC is supported on Python 2.7+ & 3.5+

# Contribution

Created by Andrew Dunai. Inspired by Nameko.

