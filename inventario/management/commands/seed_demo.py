import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from inventario.models import Category, Estanteria, Product, StockMovement, Supplier, Zona

CATEGORIAS = ['Electrónica', 'Papelería', 'Limpieza', 'Herramientas', 'Alimentación']

PROVEEDORES = [
    ('Distribuciones Ibérica S.L.', 'pedidos@distiberica.es', '912 345 678'),
    ('Suministros Levante S.A.', 'ventas@sumlevante.es', '963 210 456'),
    ('Mayorista del Norte', 'comercial@mayoristanorte.es', '944 876 123'),
    ('TecnoMarket España', 'info@tecnomarket.es', '934 567 890'),
    ('Almacenes García e Hijos', 'contacto@almacenesgarcia.es', '954 123 987'),
]

# (nombre, sku, índice categoría, índice proveedor, precio, stock_minimo, dejar bajo mínimo)
PRODUCTOS = [
    ('Auriculares Bluetooth', 'ELE-001', 0, 3, '29.90', 10, False),
    ('Cargador USB-C 65W', 'ELE-002', 0, 3, '24.50', 15, False),
    ('Cable HDMI 2 m', 'ELE-003', 0, 0, '8.95', 20, False),
    ('Ratón inalámbrico', 'ELE-004', 0, 3, '14.99', 12, True),
    ('Teclado mecánico', 'ELE-005', 0, 3, '49.00', 8, False),
    ('Memoria USB 64 GB', 'ELE-006', 0, 0, '9.50', 25, False),
    ('Cuaderno A4 cuadros', 'PAP-001', 1, 1, '2.35', 40, False),
    ('Bolígrafos azules (caja 50)', 'PAP-002', 1, 1, '11.20', 15, True),
    ('Folios A4 500 hojas', 'PAP-003', 1, 1, '4.80', 60, False),
    ('Carpeta archivadora', 'PAP-004', 1, 4, '3.15', 30, False),
    ('Rotuladores fluorescentes', 'PAP-005', 1, 4, '5.60', 20, False),
    ('Grapadora metálica', 'PAP-006', 1, 4, '7.25', 10, False),
    ('Lejía 5 L', 'LIM-001', 2, 2, '2.99', 25, False),
    ('Detergente líquido 4 L', 'LIM-002', 2, 2, '8.75', 20, False),
    ('Fregasuelos 1,5 L', 'LIM-003', 2, 2, '2.45', 30, True),
    ('Bayetas microfibra (pack 6)', 'LIM-004', 2, 4, '4.20', 25, False),
    ('Bolsas de basura 100 L', 'LIM-005', 2, 4, '6.30', 20, False),
    ('Papel higiénico 12 rollos', 'LIM-006', 2, 2, '5.95', 40, False),
    ('Taladro percutor 750 W', 'HER-001', 3, 0, '59.90', 5, False),
    ('Juego de destornilladores', 'HER-002', 3, 0, '16.80', 10, False),
    ('Martillo 500 g', 'HER-003', 3, 4, '9.40', 8, True),
    ('Cinta métrica 5 m', 'HER-004', 3, 4, '4.95', 15, False),
    ('Alicates universales', 'HER-005', 3, 0, '8.20', 10, False),
    ('Caja de tornillos surtidos', 'HER-006', 3, 1, '12.50', 12, False),
    ('Aceite de oliva virgen extra 1 L', 'ALI-001', 4, 2, '8.49', 30, False),
    ('Café molido 500 g', 'ALI-002', 4, 2, '4.95', 25, False),
    ('Galletas María (pack 4)', 'ALI-003', 4, 1, '2.20', 35, True),
    ('Arroz redondo 1 kg', 'ALI-004', 4, 2, '1.65', 50, False),
    ('Pasta espaguetis 500 g', 'ALI-005', 4, 1, '1.10', 60, False),
    ('Agua mineral 1,5 L (pack 6)', 'ALI-006', 4, 4, '2.70', 40, False),
]

# zona -> estanterías, y categoría (índice) -> estanterías donde se reparten sus productos
ZONAS = {'Pasillo A': ['Estantería 1', 'Estantería 2'],
         'Pasillo B': ['Estantería 1', 'Estantería 2', 'Estantería 3'],
         'Zona frío': ['Estantería 1', 'Estantería 2']}
UBICACION_CATEGORIA = {0: [('Pasillo A', 'Estantería 1'), ('Pasillo A', 'Estantería 2')],
                       1: [('Pasillo B', 'Estantería 1')],
                       2: [('Pasillo B', 'Estantería 2')],
                       3: [('Pasillo B', 'Estantería 3')],
                       4: [('Zona frío', 'Estantería 1'), ('Zona frío', 'Estantería 2')]}
SIN_UBICAR = {'ELE-006', 'PAP-006', 'LIM-006', 'HER-006', 'ALI-006'}  # se dejan en la bandeja "Sin ubicar"

NOTAS_ENTRADA = ['Reposición proveedor', 'Pedido recibido', 'Entrada de albarán', 'Compra mensual', 'Stock inicial']
NOTAS_SALIDA = ['Venta mostrador', 'Pedido cliente', 'Consumo interno', 'Venta online', 'Salida a tienda']


class Command(BaseCommand):
    help = 'Rellena la base de datos con datos de demo (idempotente). --reset borra el inventario antes.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Borra movimientos, productos, proveedores y categorías (no usuarios).')

    @transaction.atomic
    def handle(self, *args, **opts):
        usuario = get_user_model().objects.filter(username='admin').first()
        if not usuario:
            raise CommandError("No existe el usuario 'admin'.")
        if opts['reset']:
            StockMovement.objects.all().delete()
            Product.objects.all().delete()
            Supplier.objects.all().delete()
            Category.objects.all().delete()

        cats = [Category.objects.get_or_create(nombre=n)[0] for n in CATEGORIAS]
        provs = [Supplier.objects.get_or_create(nombre=n, defaults={'email': e, 'telefono': t})[0]
                 for n, e, t in PROVEEDORES]

        rnd = random.Random(42)
        ahora = timezone.now()
        nuevos = movs = 0
        for nombre, sku, c, p, precio, minimo, bajo in PRODUCTOS:
            prod, creado = Product.objects.get_or_create(
                sku=sku,
                defaults={'nombre': nombre, 'category': cats[c], 'supplier': provs[p],
                          'precio': precio, 'stock_minimo': minimo, 'stock': 0},
            )
            if not creado:
                continue  # movimientos solo para productos nuevos: evita duplicarlos al re-ejecutar
            nuevos += 1
            plan = [(StockMovement.ENTRADA, rnd.randint(minimo * 3, minimo * 6))]
            for _ in range(rnd.randint(1, 3)):
                plan.append((rnd.choice([StockMovement.ENTRADA, StockMovement.SALIDA, StockMovement.SALIDA]),
                             rnd.randint(1, max(2, minimo))))
            dias = sorted(rnd.sample(range(1, 90), len(plan)), reverse=True)
            stock = 0
            pasos = []
            for (tipo, cant), d in zip(plan, dias):
                if tipo == StockMovement.SALIDA:
                    cant = min(cant, stock)
                    if cant == 0:
                        continue
                stock += cant if tipo == StockMovement.ENTRADA else -cant
                pasos.append((tipo, cant, d))
            # ajuste final: bajo mínimo (alerta) o holgado
            if bajo and stock > minimo:
                pasos.append((StockMovement.SALIDA, stock - rnd.randint(0, minimo), 0))
            elif not bajo and stock <= minimo * 2:
                pasos.append((StockMovement.ENTRADA, minimo * 2 + rnd.randint(1, minimo) - stock, 0))
            for tipo, cant, d in pasos:
                # misma lógica que MovementCreate.form_valid
                producto = Product.objects.select_for_update().get(pk=prod.pk)
                if tipo == StockMovement.SALIDA and cant > producto.stock:
                    continue
                delta = cant if tipo == StockMovement.ENTRADA else -cant
                Product.objects.filter(pk=prod.pk).update(stock=F('stock') + delta)
                mov = StockMovement.objects.create(
                    product=prod, tipo=tipo, cantidad=cant, usuario=usuario,
                    nota=rnd.choice(NOTAS_ENTRADA if tipo == StockMovement.ENTRADA else NOTAS_SALIDA))
                # fecha es auto_now_add: se reescribe con update
                StockMovement.objects.filter(pk=mov.pk).update(
                    fecha=ahora - timedelta(days=d, hours=rnd.randint(0, 10), minutes=rnd.randint(0, 59)))
                movs += 1

        # almacén: get_or_create por nombre; solo se ubican productos que no tienen ubicación
        estanterias = {}
        for orden, (zona_nombre, nombres) in enumerate(ZONAS.items()):
            zona = Zona.objects.get_or_create(nombre=zona_nombre, defaults={'orden': orden})[0]
            for i, nombre in enumerate(nombres):
                estanterias[zona_nombre, nombre] = Estanteria.objects.get_or_create(
                    zona=zona, nombre=nombre, defaults={'orden': i})[0]
        ubicados = 0
        vistos = {}
        for nombre, sku, c, *_ in PRODUCTOS:
            n = vistos[c] = vistos.get(c, -1) + 1
            if sku in SIN_UBICAR:
                continue
            destinos = UBICACION_CATEGORIA[c]
            ubicados += Product.objects.filter(sku=sku, ubicacion__isnull=True).update(
                ubicacion=estanterias[destinos[n % len(destinos)]])
        self.stdout.write(self.style.SUCCESS(
            f'Productos nuevos: {nuevos}, movimientos nuevos: {movs}, productos ubicados: {ubicados}.'))
