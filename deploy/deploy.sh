#!/usr/bin/env bash
# Ejecutar como root desde /srv/inventario-django (tras git clone y crear .env). Idempotente.
set -euo pipefail
cd /srv/inventario-django

[ -d venv ] || python3 -m venv venv
venv/bin/pip install -q -r requirements.txt

set -a; . ./.env; set +a
venv/bin/python manage.py migrate --noinput
venv/bin/python manage.py collectstatic --noinput

# seed_demo requiere el usuario 'admin' (createsuperuser); solo se ejecuta si no hay productos
if venv/bin/python manage.py shell -c "import sys; from inventario.models import Product; sys.exit(Product.objects.exists())"; then
  venv/bin/python manage.py seed_demo || echo "seed_demo omitido (crea antes el usuario admin con createsuperuser)."
fi

# SQLite necesita escribir en la base de datos y en su carpeta
chown www-data:www-data /srv/inventario-django /srv/inventario-django/db.sqlite3
chown -R www-data:www-data /srv/inventario-django/staticfiles

systemctl restart inventario
