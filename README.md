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

## Despliegue en Render

### Preparación

1. Asegúrate de que tu código esté en GitHub
2. Crea una cuenta en [Render.com](https://render.com)

### Pasos para desplegar

1. **Conectar GitHub**
   - Ve a Render Dashboard
   - Haz clic en "New +" → "Blueprint"
   - Conecta tu repositorio de GitHub

2. **Configurar Variables de Entorno**
   En el dashboard de Render, configura las siguientes variables:
   
   ```
   ALLOWED_HOSTS=your-app-name.onrender.com
   EMAIL_HOST_USER=tu-correo@gmail.com
   EMAIL_HOST_PASSWORD=tu-contraseña-de-aplicación
   ```

3. **Crear Base de Datos**
   - Render creará automáticamente una base de datos PostgreSQL
   - La URL se configurará automáticamente en `DATABASE_URL`

4. **Despliegue Automático**
   - Render detectará el archivo `render.yaml`
   - Ejecutará el `build.sh` automáticamente
   - El servicio estará disponible en: `https://your-app-name.onrender.com`

### Notas Importantes

- **Cámara del navegador**: La funcionalidad de cámara del conductor requiere HTTPS (Render lo provee automáticamente)
- **Primer despliegue**: Puede tardar 5-10 minutos
- **Plan gratuito**: El servicio se duerme después de 15 minutos de inactividad
- **Migraciones**: Se ejecutan automáticamente en cada despliegue

### Crear Superusuario en Producción

Después del primer despliegue, necesitas crear un usuario administrador:

1. Ve a tu dashboard de Render
2. Selecciona tu servicio web
3. Ve a "Shell" en el menú lateral
4. Ejecuta:
```bash
python manage.py createsuperuser
```

### Configurar Correo en Gmail

Para que funcione el sistema de recuperación de contraseña:

1. Ve a tu cuenta de Google
2. Activa la verificación en 2 pasos
3. Ve a "Contraseñas de aplicación"
4. Genera una contraseña para "EyeGuard"
5. Usa esa contraseña en `EMAIL_HOST_PASSWORD`

## Desarrollo Local

Para desarrollo local, crea un archivo `.env` basado en `.env.example`:

```bash
cp .env.example .env
```

Edita `.env` con tus configuraciones locales.

## Licencia

Este proyecto está bajo la Licencia MIT.