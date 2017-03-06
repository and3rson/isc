=====
Usage
=====

Comprehensive example
=====================

`server.py`

.. include:: ../../../examples/test_server.py
   :literal:

`client.py`

.. include:: ../../../examples/test_misc.py
   :literal:

Testing
=======

The tests can be executed using py.test:

.. code-block:: bash

    make test

Caveats
=======

If you import anything from :code:`isc.server`, keep in mind that
this library uses :code:`gevent` to patch built-in libraries. This
doesn't apply to :code:`isc.client` though.
