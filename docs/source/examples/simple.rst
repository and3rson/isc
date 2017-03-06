======================
Simple server & client
======================

.. code-block:: python

    # users_service.py

    from isc.server import Node, expose

    class UserService(object):
        name = 'users'
        
        @expose
        def get_user(self, id):
            if id == 1:
                return 'Andrew'
            elif id == 2:
                return 'Victoria'
            return None

    node = Node()
    node.register_service(UserService())
    try:
        node.run()
    except KeyboardInterrupt:
        node.stop()

.. code-block:: python

    # app.py

    from isc.client import Client

    client = Client()

    print(client.users.get_user(1))  # prints 'Andrew'
    print(client.users.get_user(2))  # prints 'Victoria'
    print(client.users.get_user(3))  # prints 'None'
