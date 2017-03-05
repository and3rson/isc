# ISC

Inter-service communication layer for Python.

Uses `AMQP` as broker and `gevent` for multiprocessing.

[![Coverage Status](https://coveralls.io/repos/github/and3rson/isc/badge.svg)](https://coveralls.io/github/and3rson/isc) [![Build Status](https://travis-ci.org/and3rson/isc.svg)](https://travis-ci.org/and3rson/isc)

# Dependencies

- `gevent`
- `pika`

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

# Communication between services

## App 1: User service
```python
class UserService(object):
    name = 'users'
    
    @expose
    def get_user(self, id):
        # Let's use some ORM to retrieve the user from DB
        user = User.objects.filter(id=id).first()
        if user:
            # User not found!
            return {'username': user.username}
        return None
        
    @on('new_message')
    def on_new_message(self, username, message):
        print('New message for user {}: {}'.format(username, message))
```

## App 2: Message service
```python
from isc.client import Client

client = Client()

class MessageService(object):
    name = 'messages'
    
    @expose
    def send_message(self, body, receipt):
        user = client.users.get_user(receipt)
        if not user:
            # User not found!
            raise Exception('Cannot send message: user not found')
        Message.objects.create(receipt=receipt, message=body)
        
        # Broadcast to all instances
        client.notify('new_message', user['username'], message)
```        
## App 3: Use case
```python
from isc.client import Client

client = Client()

# ...

try:
    client.messages.send_message('Hello!', some_user_id)
except RemoteException as e:
    print('Failed to send message, error was: {}'.format(str(e)))
else:
    print('Message send!')
```

# Contribution

Created by Andrew Dunai. Inspired by Nameko.
