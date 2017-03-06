import pickle
import json


class AbstractCodec(object):
    def encode(self, message):  # pragma: no cover
        raise NotImplementedError()

    def decode(self, payload):  # pragma: no cover
        raise NotImplementedError()


class PickleCodec(AbstractCodec):
    content_type = 'pickle'

    def encode(self, message):
        return pickle.dumps(message)

    def decode(self, payload):
        return pickle.loads(payload)


class JSONCodec(AbstractCodec):
    content_type = 'json'

    def encode(self, message):
        return json.dumps(message)

    def decode(self, payload):
        return json.loads(payload)
