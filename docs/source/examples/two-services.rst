============
Two services
============

.. code-block:: python

    # users_service.py

    from isc.server import Node, expose, on
    from superapp.models import User

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

    node = Node()
    node.register_service(UserService())
    try:
        node.run()
    except KeyboardInterrupt:
        node.stop()

.. code-block:: python

    # messages_service.py

    from isc.server import Node, expose
    from isc.client import Client
    from superapp.models import Message

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

    node = Node()
    node.register_service(MessageService())
    try:
        node.run()
    except KeyboardInterrupt:
        node.stop()

.. code-block:: python

    # app.py

    from isc.client import Client

    client = Client()

    # ...

    try:
        client.messages.send_message('Hello!', some_user_id)
    except RemoteException as e:
        print('Failed to send message, error was: {}'.format(str(e)))
    else:
        print('Message send!')
