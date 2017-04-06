#!/usr/bin/env python3.6

from isc.client import Client

# import socket
# socket.setdefaulttimeout(1)

client = Client(host='127.0.0.1', exchange='isctest')
client.start()

client.set_invoke_timeout(10)

future1 = client.example.add.call_async(1, 2, wait=5)
# import time; time.sleep(5)
future2 = client.example.add.call_async(3, 4, wait=3)
# print('CORRECT!')
# import time; time.sleep(1)
# assert client.example.add(2, 3) == 5

print('Now wait...')

future2.wait()
assert future2.value == 7
future1.wait()
assert future1.value == 3

client.stop()
