from isc.client import FutureResult, RemoteException

try:
    from unittest.mock import patch
except:
    import mock


class FakeInvocationProxy(object):
    def __init__(self, service, method, fn):
        self.service = service
        self.method = method
        self.fn = fn

    def __call__(self, *args, **kwargs):
        future = FutureResult('{}.{}'.format(self.service, self.method))
        try:
            if callable(self.fn):
                result = self.fn(*args, **kwargs)
            else:
                result = self.fn
            future.resolve(result)
        except Exception as e:
            future.reject(RemoteException(str(e)))
        return future


def patch_isc(service, method, side_effect):
    """
    Patch ISC return for specifict method.
    side_effect can be callable or value.
    """
    def decorator(fn):
        def wrapper(*args, **kwargs):
            with patch(
                'isc.client.Client.invoke_async',
                side_effect=FakeInvocationProxy(service, method, side_effect)
            ):
                return fn(*args, **kwargs)
        return wrapper
    return decorator
