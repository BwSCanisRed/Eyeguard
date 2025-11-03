# EyeGuard

Sistema inteligente de monitoreo de conductores que utiliza inteligencia artificial para detectar signos de fatiga y somnolencia en tiempo real, mejorando la seguridad vial.

## Características

- Detección de fatiga en tiempo real usando visión por computadora
- Monitoreo 24/7 con alertas inmediatas
- Dashboard administrativo para gestión de conductores
- Sistema de reportes y eventos críticos
- Interfaz web responsive

## Requisitos

- Python 3.10+
- Django 5.1.3
- OpenCV
- MediaPipe
- PostgreSQL

## Instalación

1. Clonar el repositorio
```bash
git clone https://github.com/BwSCanisRed/Eyeguard.git
cd Eyeguard
```

2. Crear un entorno virtual
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

3. Instalar dependencias
```bash
pip install -r requirements.txt
```

4. Configurar la base de datos
```bash
python manage.py migrate
```

5. Crear usuario administrador
```bash
python create_admin.py
```

6. Ejecutar el servidor de desarrollo
```bash
python manage.py runserver
```

## Uso

1. Acceder al sistema en `http://localhost:8000`
2. Iniciar sesión como administrador:
   - Usuario: admin
   - Contraseña: admin123
3. Registrar conductores y vehículos
4. Monitorear el estado de fatiga en tiempo real

## Licencia

Este proyecto está bajo la Licencia MIT.