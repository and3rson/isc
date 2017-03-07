import pickle
import json


class AbstractCodec(object):
    """
    Abstract base class for implementing codecs.

    "Codec" is a class that tells ISC how to encode & decode message payloads.

    Server can support multiple codecs while client can use only one at a time.

    Default codec is :class:`.PickleCodec`. You can implement your own codec
    by extending :class:`.AbstractCodec` and overriding its methods.

    Important: Don't forget that both client and server should have the codec installed!
    """
    def encode(self, message):  # pragma: no cover
        """
        Called when a message needs to be serialized
        for sending over AMQP channel.
        """
        raise NotImplementedError()

    def decode(self, payload):  # pragma: no cover
        """
        Called when a message needs to be serialized
        for sending over AMQP channel.
        """
        raise NotImplementedError()


class PickleCodec(AbstractCodec):
    """
    Pickle codec implementation.
    """
    content_type = 'pickle'

    def encode(self, message):
        return pickle.dumps(message)

    def decode(self, payload):
        return pickle.loads(payload)


class JSONCodec(AbstractCodec):
    """
    JSON codec implementation.
    """
    content_type = 'json'

    def encode(self, message):
        return json.dumps(message)

    def decode(self, payload):
        return json.loads(payload)
