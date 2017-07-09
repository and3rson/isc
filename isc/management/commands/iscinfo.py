import sys
from inspect import signature

try:  # Python 2.x
    from StringIO import StringIO
except ImportError:  # Python 3.x
    from io import StringIO

from django.core.management import BaseCommand
from django.conf import settings
from importlib import import_module


class Command(BaseCommand):
    TAB = ' ' * 4
    GREEN = '\033[32m'
    BOLD_GREEN = '\033[1;32m'
    BOLD_YELLOW = '\033[1;33m'
    BOLD_BLUE = '\033[1;34m'
    RESET = '\033[0m'

    def handle(self, *args, **kwargs):
        for service_string, service, methods in self.get_services():
            self.print_service_info(service_string, service, methods)

    def get_services(self):
        for service_string in settings.ISC['services']:
            service = self._import_service(service_string)
            yield (service_string, service, list(self._get_service_methods(service)))

    def _import_service(self, service_string):
        module_name, _, class_name = service_string.rpartition('.')
        module = import_module(module_name)
        return getattr(module, class_name)

    def _get_service_methods(self, service):
        for attr in dir(service):
            fn = getattr(service, attr)
            if hasattr(fn, '__exposed__'):
                yield fn

    def print_service_info(self, service_string, service, methods):
        service_module, _, service_class = service_string.rpartition('.')
        sys.stdout.write(Command.GREEN + service_module + '.' + Command.BOLD_GREEN + service_class + Command.RESET + ': ')
        sys.stdout.write(Command.BOLD_BLUE + service.name + Command.RESET + '\n')
        for method in methods:
            self.print_method_info(method)

    def print_method_info(self, method):
        fn_str = Command.BOLD_YELLOW + method.__name__ + Command.RESET + str(signature(method))
        sys.stdout.write(
            Command.TAB + '- ' + fn_str + '\n'
        )
