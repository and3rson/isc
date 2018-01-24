import sys
import pickle
import json
from uuid import UUID
from datetime import datetime

from dateutil import parser

# pylint: disable=invalid-name,undefined-variable
if sys.version_info > (3, 0):
    # Python 3.x
    text_type = str
    binary_type = bytes
else:
    # Python 2.x
    text_type = unicode  # noqa
    binary_type = str
# pylint: enable=invalid-name,undefined-variable


class CodecException(Exception):
    pass


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
        return pickle.dumps(message, protocol=2)

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


class TypedJSONCodec(AbstractCodec):
    """
    JSON codec implementation with support of timestamps & UUIDs.
    """
    content_type = 'typedjson'

    def encode(self, message):
        encoder = json.JSONEncoder(default=self._encode_object)
        return encoder.encode(message)

    def _encode_object(self, v):
        print('Encode', v)
        if isinstance(v, datetime):
            return dict(__object_type='datetime', __object_value=v.isoformat())
        elif isinstance(v, UUID):
            return dict(__object_type='uuid', __object_value=v.hex)
        elif isinstance(v, binary_type):
            return dict(__object_type='binary', __object_value=list(v))
        else:
            raise CodecException('Don\'t know how to serialize {}'.format(repr(v)))

    def decode(self, payload):
        if isinstance(payload, binary_type):
            payload = payload.decode('utf-8')
        return json.JSONDecoder(object_hook=self._decode_object).decode(payload)

    def _decode_object(self, v):
        try:
            obj_type = v['__object_type']
            obj_value = v['__object_value']
        except Exception:
            return v

        if obj_type == 'datetime':
            return parser.parse(obj_value)
        elif obj_type == 'uuid':
            return UUID(obj_value)
        elif obj_type == 'binary':
            return bytes(bytearray(obj_value))  # Python 2.x/3.x portable method
        else:
            raise CodecException('Unknown type: {}'.format(obj_type))

