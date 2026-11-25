# Sistema de Inventario

Aplicación web en Django (5.2, SQLite) para controlar el stock de productos y sus movimientos. Interfaz en español, con login obligatorio.

## Funcionalidades

- **Productos** con estado de stock (normal / stock bajo respecto al mínimo) y medidor visual; búsqueda, filtros por categoría y proveedor, y paginación.
- **Categorías y proveedores** (CRUD completo).
- **Movimientos de entrada y salida** con control de stock: el stock se actualiza de forma atómica, una salida mayor que el stock se rechaza y los movimientos no se editan ni se borran.
- **Importación CSV** de productos (ver formato abajo) con plantilla descargable.
- **Dashboard y gráficos** (ECharts, vendorizado: no necesita CDN) con alertas de stock mínimo en todas las páginas.
- **Almacén** con zonas y estanterías, y ubicación de productos arrastrando y soltando.
- Formularios y confirmaciones en **modales**.

## Ejecutar en local

```
python -m venv venv
venv\Scripts\activate          # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo
python manage.py runserver
```

Abrir http://127.0.0.1:8000/ e iniciar sesión. Tests: `python manage.py test`.

## Usuarios y datos demo

`seed_demo` **no crea ningún usuario**: exige que exista uno llamado `admin`, así que créalo antes con `python manage.py createsuperuser` (usuario `admin`) y elige tu propia contraseña.
Después carga datos de ejemplo (idempotente; `--reset` borra antes el inventario, no los usuarios): 5 categorías, 5 proveedores, 30 productos con sus movimientos de los últimos 90 días (algunos bajo el stock mínimo), y 3 zonas con sus estanterías con los productos repartidos (algunos quedan "Sin ubicar").

## Variables de entorno

| Variable | Por defecto | Descripción |
|---|---|---|
| `DJANGO_DEBUG` | `1` | `0` en producción. |
| `DJANGO_SECRET_KEY` | clave de desarrollo | Obligatoria si `DJANGO_DEBUG=0`. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` (solo en debug) | Hosts/IP separados por comas. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | vacío | Orígenes separados por comas, p. ej. `http://1.2.3.4:8080`. |
| `DJANGO_HTTPS` | `0` | Con `DJANGO_DEBUG=0`, `1` marca las cookies de sesión/CSRF como Secure. Ponlo a `1` solo si se sirve por HTTPS; con HTTP el login no funcionaría. |

## Formato del CSV de importación

Codificación UTF-8, separador `;` o `,`, máximo 1 MB y 2000 filas. Cabecera obligatoria:

```
nombre;sku;categoria;proveedor;precio;stock;stock_minimo
Cable HDMI 2 m;ELE-100;Electrónica;TecnoMarket España;8.95;20;5
```

Todos los campos son obligatorios; `precio` ≥ 0 con decimales, `stock` y `stock_minimo` enteros ≥ 0; el `sku` no puede repetirse en el archivo. Un `sku` existente se actualiza (conservando su stock actual); categorías y proveedores inexistentes se crean. Si hay errores no se importa nada y se indican por fila.

## Despliegue en un droplet Ubuntu (nginx + gunicorn, sin dominio ni HTTPS)

Acceso por `http://IP:8080` (el puerto 80 queda libre para otra aplicación).

```
apt update && apt install -y python3-venv nginx git
git clone <URL-del-repositorio> /srv/inventario-django
cd /srv/inventario-django
cp deploy/.env.example .env      # editar: SECRET_KEY, IP en ALLOWED_HOSTS y CSRF_TRUSTED_ORIGINS
cp deploy/inventario.service /etc/systemd/system/
ln -sf /srv/inventario-django/deploy/inventario.nginx /etc/nginx/sites-enabled/inventario
systemctl daemon-reload && systemctl enable inventario
bash deploy/deploy.sh            # venv, dependencias, migrate, collectstatic, permisos, arranca el servicio
nginx -t && systemctl reload nginx
ufw allow 8080
```

Crear el primer usuario (como root, con el entorno cargado):

```
cd /srv/inventario-django && set -a && . ./.env && set +a
venv/bin/python manage.py createsuperuser
chown www-data:www-data db.sqlite3
bash deploy/deploy.sh            # ahora sí carga los datos demo (solo si no hay productos)
```

Para actualizar: `git pull && bash deploy/deploy.sh`. `deploy.sh` es idempotente (venv, dependencias, migraciones, collectstatic, permisos de SQLite y reinicio del servicio); carga los datos demo solo si no hay productos y existe el usuario `admin`.
