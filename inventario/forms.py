import csv
import io
import re
from decimal import Decimal, InvalidOperation

from django import forms
from django.db import transaction

from .models import Category, Estanteria, Product, Supplier, Zona

COLUMNAS = ['nombre', 'sku', 'categoria', 'proveedor', 'precio', 'stock', 'stock_minimo']
MAX_BYTES = 1024 * 1024
MAX_FILAS = 2000
MAX_ERRORES = 20
MAX_INT = 2147483647
# columna -> longitud máxima en el modelo
MAX_LEN = {'nombre': 150, 'sku': 50, 'categoria': 100, 'proveedor': 150}


def agrupar_ubicaciones(campo):
    """Select de estanterías con <optgroup> por zona y opción vacía 'Sin ubicar'."""
    grupos = [('', 'Sin ubicar')]
    for z in Zona.objects.prefetch_related('estanterias'):
        if z.estanterias.all():
            grupos.append((z.nombre, [(e.pk, e.nombre) for e in z.estanterias.all()]))
    campo.choices = grupos


class ProductoUbicadoField(forms.ModelChoiceField):
    def label_from_instance(self, p):
        return f'{p.nombre} ({p.sku}) · ahora en: {p.ubicacion or "Sin ubicar"}'


class MoverForm(forms.Form):
    """Mueve un producto a una estantería. La vista elimina el campo que ya viene fijado."""
    producto = ProductoUbicadoField(Product.objects.select_related('ubicacion__zona'), label='Producto')
    estanteria = forms.ModelChoiceField(Estanteria.objects.all(), required=False, label='Destino')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        agrupar_ubicaciones(self.fields['estanteria'])


def _entero(valor):
    if not re.fullmatch(r'[0-9]+', valor) or int(valor) > MAX_INT:
        raise ValueError
    return int(valor)


def _precio(valor):
    try:
        d = Decimal(valor.replace(',', '.'))
    except InvalidOperation:
        raise ValueError
    if not d.is_finite() or d < 0 or d >= 10 ** 8:
        raise ValueError
    return d.quantize(Decimal('0.01'))


class ProductImportForm(forms.Form):
    archivo = forms.FileField(label='Archivo CSV')

    def clean_archivo(self):
        f = self.cleaned_data['archivo']
        if f.size > MAX_BYTES:
            raise forms.ValidationError('El archivo supera 1 MB.')
        try:
            texto = f.read().decode('utf-8-sig')
        except UnicodeDecodeError:
            raise forms.ValidationError('El archivo debe estar codificado en UTF-8.')
        primera = texto.lstrip().split('\n', 1)[0]
        delim = ';' if primera.count(';') > primera.count(',') else ','
        reader = csv.DictReader(io.StringIO(texto, newline=''), delimiter=delim)
        try:
            reader.fieldnames = [(c or '').strip().lower() for c in reader.fieldnames or []]
            faltan = [c for c in COLUMNAS if c not in reader.fieldnames]
            if faltan:
                raise forms.ValidationError(
                    f'Cabecera incorrecta, faltan columnas: {", ".join(faltan)}.')
            filas = list(reader)
        except csv.Error as e:
            raise forms.ValidationError(f'CSV no válido: {e}')
        if not filas:
            raise forms.ValidationError('El archivo no contiene filas de datos.')
        if len(filas) > MAX_FILAS:
            raise forms.ValidationError(f'Máximo {MAX_FILAS} filas por archivo.')

        errores, datos, vistos = [], [], {}
        for n, fila in enumerate(filas, start=2):  # fila 1 = cabecera
            v = {c: (fila.get(c) or '').strip() for c in COLUMNAS}
            if not any(v.values()):
                continue
            problemas = [f'{c} vacío' for c in COLUMNAS if not v[c]]
            problemas += [f'{c} demasiado largo (máx. {m})' for c, m in MAX_LEN.items() if len(v[c]) > m]
            for c, conv in (('precio', _precio), ('stock', _entero), ('stock_minimo', _entero)):
                if v[c]:
                    try:
                        v[c] = conv(v[c])
                    except ValueError:
                        problemas.append(f'{c} no válido (debe ser un número ≥ 0'
                                         f'{"" if c == "precio" else " entero"})')
            if v['sku'] in vistos:
                problemas.append(f'sku duplicado (ya aparece en la fila {vistos[v["sku"]]})')
            vistos.setdefault(v['sku'], n)
            if problemas:
                errores.append(f'Fila {n}: {"; ".join(problemas)}.')
            datos.append(v)
        if not datos and not errores:
            raise forms.ValidationError('El archivo no contiene filas de datos.')
        if errores:
            extra = len(errores) - MAX_ERRORES
            if extra > 0:
                errores = errores[:MAX_ERRORES] + [f'... y {extra} fila(s) más con errores.']
            raise forms.ValidationError(errores)
        return datos

    @transaction.atomic
    def importar(self):
        """Devuelve (creados, actualizados). Un sku existente conserva su stock."""
        filas = self.cleaned_data['archivo']
        cats, provs = {}, {}
        existentes = Product.objects.in_bulk([f['sku'] for f in filas], field_name='sku')
        nuevos, cambiados = [], []
        for f in filas:
            if f['categoria'] not in cats:
                # sin distinguir mayúsculas; filter().first() por si ya hubiera duplicados históricos
                cats[f['categoria']] = (Category.objects.filter(nombre__iexact=f['categoria']).first()
                                        or Category.objects.create(nombre=f['categoria']))
            if f['proveedor'] not in provs:
                # nombre no es único en Supplier: get_or_create fallaría con duplicados
                provs[f['proveedor']] = (Supplier.objects.filter(nombre=f['proveedor']).first()
                                         or Supplier.objects.create(nombre=f['proveedor']))
            campos = dict(nombre=f['nombre'], category=cats[f['categoria']], supplier=provs[f['proveedor']],
                          precio=f['precio'], stock_minimo=f['stock_minimo'])
            p = existentes.get(f['sku'])
            if p:
                for k, val in campos.items():
                    setattr(p, k, val)
                cambiados.append(p)
            else:
                nuevos.append(Product(sku=f['sku'], stock=f['stock'], **campos))
        Product.objects.bulk_create(nuevos)
        Product.objects.bulk_update(cambiados, ['nombre', 'category', 'supplier', 'precio', 'stock_minimo'])
        return len(nuevos), len(cambiados)
