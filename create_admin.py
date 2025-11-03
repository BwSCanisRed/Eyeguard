import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Eyeguard.settings')
django.setup()

from core.models import Usuario

def create_admin():
    try:
        admin = Usuario.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='admin123',
            rol='admin'
        )
        print("Administrador creado exitosamente!")
        print("Usuario: admin")
        print("Contraseña: admin123")
    except Exception as e:
        print(f"Error al crear el administrador: {e}")

if __name__ == '__main__':
    create_admin()