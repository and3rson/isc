from functools import wraps

from isc.client import FutureResult, RemoteException

try:
    from unittest.mock import patch
except ImportError:
    from mock import patch


class FakeInvocationProxy(object):
    def __init__(self, definitions):
        self.definitions = definitions

    def __call__(self, service, method, *args, **kwargs):
        def_key = '{}.{}'.format(service, method)
        assert \
            def_key in self.definitions, \
            'Your code tried to call "{}" which is not present in `patch_isc` definition.'.format(
                def_key
            )
        def_value = self.definitions[def_key]
        print('FakeInvocationProxy: calling {}.{}(*{}, **{})'.format(
            service,
            method,
            repr(args),
            repr(kwargs)
        ))
        future = FutureResult('{}.{}'.format(service, method))
        try:
            if callable(def_value):
                result = def_value(*args, **kwargs)
            else:
                result = def_value
            future.resolve(result)
        except Exception as e:
            future.reject(RemoteException(str(e)))
        return future


def patch_isc(definitions):
    """
    Patch ISC return for specified methods.
    `definitions` should be a dictionary where each key
    is a string in "service.method" form and each value
    is a predefined return value or a callable.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with patch(
                'isc.client.Client.invoke_async',
                side_effect=FakeInvocationProxy(definitions)
            ):
                return fn(*args, **kwargs)
        return wrapper
    return decorator
