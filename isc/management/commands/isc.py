from django.core.management import BaseCommand
from django.conf import settings
from isc.server import Node
from importlib import import_module


class Command(BaseCommand):
    def _import_object(self, import_string):
        module_name, _, object_name = import_string.rpartition('.')
        module = import_module(module_name)
        return getattr(module, object_name)

    def handle(self, *args, **kwargs):
        assert getattr(settings, 'ISC', None), 'ISC config not present in settings'
        assert 'hostname' in settings.ISC, 'hostname not provided in ISC config'
        assert 'services' in settings.ISC, 'services not provided in ISC config'

        node = Node(hostname=settings.ISC['hostname'])

        for service_import_string in settings.ISC['services']:
            service_class = self._import_object(service_import_string)
            node.register_service(service_class())

        for hook_name, hook_import_string in settings.ISC.get('hooks', {}).items():
            hook_function = self._import_object(hook_import_string)
            node.add_hook(hook_name)(hook_function)

        node.run()
