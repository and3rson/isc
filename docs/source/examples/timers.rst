======================
Timers
======================

.. code-block:: python

    # tick_service.py

    from isc.server import Node, expose, local_timer

    class TickerService(object):
        name = 'ticker'

        def __init__(self):
            """
            WARNING:
            Do NOT do this in real projects. (I'm speaking about local state
            which is represented by `self.ticks` attribute here.)

            Services MUST be stateless.
            This dirty trick right here is used just to demonstrate
            how the timer works without involving any external storage.

            In real project:
            - ALWAYS database or any other external storage instead of `self`
            - NEVER mutate service object.

            So in real project you would have done something like this:
            self.db_conn = SomeDatabaseConnection()
            # ...
            spam = next(self.db_conn.query('SELECT spam;').fetchone(), None)
            """

            self.ticks = 0

        @expose
        def get_ticks(self, id):
            return self.ticks

        @expose
        def reset_ticks(self):
            self.ticks = 0

        @local_timer(timeout=5)
        def local_timer(self):
            self.ticks += 1


    node = Node()
    node.register_service(TickerService())
    try:
        node.run()
    except KeyboardInterrupt:
        node.stop()

.. code-block:: python

    # app.py

    from isc.client import Client
    from time import sleep

    client = Client()

    client.ticker.reset_ticks()
    print(client.ticker.get_ticks())  # prints 0

    sleep(10)
    print(client.ticker.get_ticks())  # prints 2

    sleep(10)
    print(client.ticker.get_ticks())  # prints 4

    client.ticker.reset_ticks()
    print(client.ticker.get_ticks())  # prints 0

    sleep(10)
    print(client.ticker.get_ticks())  # prints 2
