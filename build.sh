#!/usr/bin/env bash
# exit on error
set -o errexit

# Instalar dependencias
pip install -r requirements.txt

# Compilar archivos de traducción (si gettext está disponible)
if command -v msgfmt &> /dev/null; then
    python manage.py compilemessages --ignore=venv
fi

# Recolectar archivos estáticos
python manage.py collectstatic --no-input

# Ejecutar migraciones
python manage.py migrate
