# Sistema de Inventario

Aplicación web en Django (5.2, SQLite) para controlar el stock de productos y sus movimientos. Interfaz en español, con login obligatorio.

## Acceso a la demo

Servicio desplegado en Render: `https://inventario-django.onrender.com` (sustituir por la URL pública real).

- Usuario: `admin`
- Contraseña: `demo-inventario-django`

Son credenciales de demostración y los datos son ficticios: se reinician cada vez que el servicio se reinicia. El plan gratuito de Render duerme el servicio tras 15 minutos sin visitas, así que la primera carga puede tardar ~1 minuto.

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
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` (solo en debug) | Hosts separados por comas (en Render: `.onrender.com`). |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | vacío | Orígenes separados por comas, p. ej. `https://inventario-django.onrender.com`. |
| `DJANGO_HTTPS` | `0` | Con `DJANGO_DEBUG=0`, `1` marca las cookies de sesión/CSRF como Secure. Ponlo a `1` solo si se sirve por HTTPS (también activa `SECURE_PROXY_SSL_HEADER` para proxys como el de Render); con HTTP el login no funcionaría. |
| `DEMO_PASSWORD` | sin definir | Contraseña del usuario `admin` en Render (la usa `crear_admin_demo`). |

## Formato del CSV de importación

Codificación UTF-8, separador `;` o `,`, máximo 1 MB y 2000 filas. Cabecera obligatoria:

```
nombre;sku;categoria;proveedor;precio;stock;stock_minimo
Cable HDMI 2 m;ELE-100;Electrónica;TecnoMarket España;8.95;20;5
```

Todos los campos son obligatorios; `precio` ≥ 0 con decimales, `stock` y `stock_minimo` enteros ≥ 0; el `sku` no puede repetirse en el archivo. Un `sku` existente se actualiza (conservando su stock actual); categorías y proveedores inexistentes se crean. Si hay errores no se importa nada y se indican por fila.

## Despliegue en Render (plan gratuito, HTTPS automático)

1. Crea una cuenta en [render.com](https://render.com) y conecta tu cuenta de GitHub.
2. **New → Blueprint**, elige este repositorio (lee `render.yaml`).
3. Escribe el valor de `DEMO_PASSWORD` (la contraseña que tendrá el usuario `admin`) y pulsa **Apply**.
4. Al terminar el build, la app queda en una URL tipo `https://inventario-django.onrender.com`. Entra con el usuario `admin` y la contraseña que pusiste en `DEMO_PASSWORD`.

`render.yaml` ya define el resto de variables (`DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY` generada, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_HTTPS=1`). Para actualizar basta con hacer `git push` a `main` (Render redespliega solo).

Avisos del plan gratuito: el servicio se duerme tras 15 min sin tráfico y tarda ~1 min en despertar; el disco es efímero, así que la base SQLite se recrea en cada arranque (migraciones, usuario `admin` vía `crear_admin_demo` y datos demo con `seed_demo`) y **los datos se reinician** cada vez. La contraseña nunca se guarda en el repositorio.
