#!/usr/bin/env python3.6

from isc.client import Client
from isc.codecs import TypedJSONCodec

# import socket
# socket.setdefaulttimeout(1)

client = Client(host='127.0.0.1', exchange='isctest')
client.start()
client.set_codec(TypedJSONCodec())

client.set_invoke_timeout(10)

assert client.invoke('example', 'add', 1, 2) == 3
# import time; time.sleep(5)
# assert client.invoke('example', 'add', 3, 4) == 7
# print('CORRECT!')
#import time; time.sleep(1)
# assert client.example.add(2, 3) == 5

client.stop()
