import subprocess
import sys

try:
    from IPython import start_ipython
    ipython = True
except ImportError:
    ipython = False

from django.core.management import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    CMD = \
        'from isc.client import Client;' \
        'from threading import Event;' \
        'rpc = Client(host="{}");' \
        'e = Event();' \
        'rpc._consumer.on_connect += e.set;' \
        'rpc.start();' \
        'e.wait();' \
        'rpc._consumer.on_connect -= e.set;' \
        'del e;' \
        'print(\'\\n\\033[1;34mINFO: You now have the global "rpc" variable.\\033[0m\\n\')'

    def handle(self, *args, **kwargs):
        if not hasattr(settings, 'ISC'):
            sys.stderr.write('Django config is missing "ISC" configuration.')
            sys.exit(1)
        if not settings.ISC['url']:
            sys.stderr.write('Django config for ISC is missing "url" key.')
            sys.exit(1)
        args = ['-i', '-c', Command.CMD.format(settings.ISC['url'])]
        if ipython:
            sys.argv = [sys.executable] + args
            start_ipython()
        else:
            ps = subprocess.Popen(
                [sys.executable] + args,
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr
            )
            ps.communicate()
            sys.exit(ps.returncode)

