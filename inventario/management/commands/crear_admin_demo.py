import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea el superusuario 'admin' con la contraseña de DEMO_PASSWORD si no existe (para despliegues demo)."

    def handle(self, *args, **opts):
        password = os.environ.get('DEMO_PASSWORD')
        if not password:
            self.stdout.write('DEMO_PASSWORD no definida: no se crea ningún usuario.')
            return
        User = get_user_model()
        if User.objects.filter(username='admin').exists():
            self.stdout.write("El usuario 'admin' ya existe.")
            return
        User.objects.create_superuser('admin', password=password)
        self.stdout.write("Usuario 'admin' creado.")
