import json
import re
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, DecimalField, F, Prefetch, ProtectedError, Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.functional import cached_property
from django.views.generic import (
    CreateView, DeleteView, DetailView, FormView, ListView, TemplateView, UpdateView, View,
)

from .forms import MoverForm, ProductImportForm, agrupar_ubicaciones
from .models import Category, Estanteria, Product, StockMovement, Supplier, Zona


class Formulario(LoginRequiredMixin, SuccessMessageMixin):
    """Plantilla común de formulario + clases Bootstrap en los campos."""
    template_name = 'inventario/form.html'
    success_message = 'Guardado correctamente.'

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for campo in form.fields.values():
            campo.widget.attrs['class'] = 'form-select' if isinstance(campo.widget, forms.Select) else 'form-control'
        if 'ubicacion' in form.fields:
            agrupar_ubicaciones(form.fields['ubicacion'])
        return form


class Borrar(LoginRequiredMixin, DeleteView):
    template_name = 'inventario/confirm_delete.html'

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, 'No se puede eliminar: tiene productos o movimientos asociados.')
            return redirect(self.success_url)
        messages.success(self.request, 'Eliminado correctamente.')
        return response


def serie_movimientos(inicio, dias, semanal=False):
    """Entradas y salidas desde `inicio` durante `dias` días; con `semanal`, agrupadas por semana (lunes)."""
    E, S = StockMovement.ENTRADA, StockMovement.SALIDA
    por_dia = {r['d']: r for r in StockMovement.objects.filter(fecha__date__gte=inicio).annotate(
        d=TruncDate('fecha')).values('d').annotate(e=Sum('cantidad', filter=Q(tipo=E)), s=Sum('cantidad', filter=Q(tipo=S)))}
    cubos = {}
    for i in range(dias):
        d = inicio + timedelta(days=i)
        clave = d - timedelta(days=d.weekday()) if semanal else d
        c = cubos.setdefault(clave, [0, 0])
        c[0] += (por_dia.get(d) or {}).get('e') or 0
        c[1] += (por_dia.get(d) or {}).get('s') or 0
    return {'labels': [k.strftime('%d/%m') for k in cubos],
            'entradas': [v[0] for v in cubos.values()], 'salidas': [v[1] for v in cubos.values()]}


def top_salidas(movs, n):
    """Los `n` productos con más unidades salidas en el queryset de movimientos."""
    # por product_id: dos productos con el mismo nombre no se fusionan
    top = movs.filter(tipo=StockMovement.SALIDA).values('product_id', 'product__nombre').annotate(
        t=Sum('cantidad')).order_by('-t', 'product__nombre', 'product_id')[:n]
    return {'labels': [r['product__nombre'] for r in top], 'valores': [r['t'] for r in top]}


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = 'inventario/home.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        hoy = timezone.localdate()
        k = Product.objects.aggregate(
            n=Count('pk'), unidades=Sum('stock'),
            valor=Sum(F('stock') * F('precio'), output_field=DecimalField(max_digits=14, decimal_places=2)),
            sin=Count('pk', filter=Q(stock=0)),
            bajo=Count('pk', filter=Q(stock__gt=0, stock__lte=F('stock_minimo'))))
        k['unidades'] = k['unidades'] or 0
        k['valor'] = k['valor'] or 0
        movs30 = StockMovement.objects.filter(fecha__date__gte=hoy - timedelta(days=29))
        k['movs30'] = movs30.count()
        cat = Product.objects.values('category__nombre').annotate(u=Sum('stock')).order_by('category__nombre')
        datos = {
            'serie': serie_movimientos(hoy - timedelta(days=13), 14),
            'top': top_salidas(movs30, 5),
            'estado': {'ok': k['n'] - k['sin'] - k['bajo'], 'bajo': k['bajo'], 'sin': k['sin']},
            'categorias': {'labels': [r['category__nombre'] for r in cat], 'valores': [r['u'] or 0 for r in cat]},
        }
        s = datos['serie']
        # tablas ocultas para lectores de pantalla (los gráficos son role="img")
        ctx['tablas'] = {
            'serie': list(zip(s['labels'], s['entradas'], s['salidas'])),
            'top': list(zip(datos['top']['labels'], datos['top']['valores'])),
            'categorias': list(zip(datos['categorias']['labels'], datos['categorias']['valores'])),
        }
        ctx.update(kpi=k, datos=datos, ultimos=StockMovement.objects.select_related('product', 'usuario')[:5])
        return ctx


# Categorías
class CategoryList(LoginRequiredMixin, ListView):
    model = Category
    template_name = 'inventario/category_list.html'


class CategoryCreate(Formulario, CreateView):
    model = Category
    fields = ['nombre']
    success_url = reverse_lazy('category_list')
    titulo = 'Nueva categoría'


class CategoryUpdate(Formulario, UpdateView):
    model = Category
    fields = ['nombre']
    success_url = reverse_lazy('category_list')
    titulo = 'Editar categoría'


class CategoryDelete(Borrar):
    model = Category
    success_url = reverse_lazy('category_list')


# Proveedores
class SupplierList(LoginRequiredMixin, ListView):
    model = Supplier
    template_name = 'inventario/supplier_list.html'


class SupplierCreate(Formulario, CreateView):
    model = Supplier
    fields = ['nombre', 'email', 'telefono']
    success_url = reverse_lazy('supplier_list')
    titulo = 'Nuevo proveedor'


class SupplierUpdate(Formulario, UpdateView):
    model = Supplier
    fields = ['nombre', 'email', 'telefono']
    success_url = reverse_lazy('supplier_list')
    titulo = 'Editar proveedor'


class SupplierDelete(Borrar):
    model = Supplier
    success_url = reverse_lazy('supplier_list')


# Productos
def id_filtro(valor):
    """Entero de hasta 9 dígitos, o None si el valor de ?param= no es válido (se ignora el filtro)."""
    return int(valor) if re.fullmatch(r'[0-9]{1,9}', valor) else None


class PaginaSegura:
    """?page= fuera de rango o no numérico -> última página válida (en vez de 404)."""
    def paginate_queryset(self, queryset, page_size):
        paginator = self.get_paginator(queryset, page_size, orphans=self.get_paginate_orphans(),
                                       allow_empty_first_page=self.get_allow_empty())
        page = paginator.get_page(self.request.GET.get(self.page_kwarg))
        return paginator, page, page.object_list, page.has_other_pages()


class ProductList(PaginaSegura, LoginRequiredMixin, ListView):
    model = Product
    template_name = 'inventario/product_list.html'
    paginate_by = 10

    def get_queryset(self):
        qs = Product.objects.select_related('category', 'supplier', 'ubicacion__zona')
        g = self.request.GET
        if (prov := id_filtro(g.get('proveedor', ''))) is not None:
            qs = qs.filter(supplier_id=prov)
        if (cat := id_filtro(g.get('categoria', ''))) is not None:
            qs = qs.filter(category_id=cat)
        if g.get('q'):
            qs = qs.filter(Q(nombre__icontains=g['q']) | Q(sku__icontains=g['q']))
        ub = g.get('ubicacion', '')
        if ub == 'sin':
            qs = qs.filter(ubicacion__isnull=True)
        elif re.fullmatch(r'[0-9]{1,9}', ub):
            qs = qs.filter(ubicacion_id=int(ub))
        estado = g.get('estado')
        if estado == 'sin':
            qs = qs.filter(stock=0)
        elif estado == 'bajo':
            qs = qs.filter(stock__gt=0, stock__lte=F('stock_minimo'))
        elif estado == 'ok':
            qs = qs.filter(stock__gt=F('stock_minimo'))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['categorias'] = Category.objects.all()
        ctx['proveedores'] = Supplier.objects.all()
        ctx['estados'] = [('sin', 'Sin stock'), ('bajo', 'Stock bajo'), ('ok', 'Correcto')]
        ctx['zonas'] = Zona.objects.prefetch_related('estanterias')
        query = self.request.GET.copy()
        query.pop('page', None)
        ctx['querystring'] = query.urlencode()
        return ctx


class ProductDetail(LoginRequiredMixin, DetailView):
    queryset = Product.objects.select_related('category', 'supplier', 'ubicacion__zona')
    template_name = 'inventario/product_detail.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['movimientos'] = self.object.stockmovement_set.select_related('usuario')[:10]
        return ctx


class ProductCreate(Formulario, CreateView):
    model = Product
    fields = ['nombre', 'sku', 'category', 'supplier', 'precio', 'stock', 'stock_minimo', 'ubicacion']
    titulo = 'Nuevo producto'


class ProductUpdate(Formulario, UpdateView):
    # sin 'stock': solo cambia mediante movimientos
    model = Product
    fields = ['nombre', 'sku', 'category', 'supplier', 'precio', 'stock_minimo', 'ubicacion']
    titulo = 'Editar producto'


class ProductDelete(Borrar):
    model = Product
    success_url = reverse_lazy('product_list')


# Almacén
def contadores():
    """Productos por estantería y zona, y totales ubicados / sin ubicar."""
    ubicados = Product.objects.filter(ubicacion__isnull=False)
    por_est = dict(ubicados.values_list('ubicacion').annotate(n=Count('pk')))
    por_zona = dict(ubicados.values_list('ubicacion__zona').annotate(n=Count('pk')))
    n_ubicados = sum(por_est.values())
    return {
        'estanterias': {e: por_est.get(e, 0) for e in Estanteria.objects.values_list('pk', flat=True)},
        'zonas': {z: por_zona.get(z, 0) for z in Zona.objects.values_list('pk', flat=True)},
        'ubicados': n_ubicados,
        'sin_ubicar': Product.objects.count() - n_ubicados,
    }


class Warehouse(LoginRequiredMixin, TemplateView):
    template_name = 'inventario/warehouse.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        productos = Prefetch('productos')
        zonas = list(Zona.objects.prefetch_related(Prefetch('estanterias', Estanteria.objects.prefetch_related(productos))))
        for z in zonas:
            z.n_productos = sum(len(e.productos.all()) for e in z.estanterias.all())
        ctx.update(zonas=zonas, sin_ubicar=list(Product.objects.filter(ubicacion__isnull=True)),
                   n_estanterias=sum(len(z.estanterias.all()) for z in zonas),
                   n_ubicados=sum(z.n_productos for z in zonas))
        return ctx


class ZoneCreate(Formulario, CreateView):
    model = Zona
    fields = ['nombre']
    success_url = reverse_lazy('warehouse')
    titulo = 'Nueva zona'


class ZoneUpdate(Formulario, UpdateView):
    model = Zona
    fields = ['nombre']
    success_url = reverse_lazy('warehouse')
    titulo = 'Renombrar zona'


class ZoneDelete(Borrar):
    model = Zona
    success_url = reverse_lazy('warehouse')
    aviso = 'Sus estanterías también se eliminarán y sus productos pasarán a «Sin ubicar». No se borra ningún producto.'


class ShelfCreate(Formulario, CreateView):
    model = Estanteria
    fields = ['nombre', 'zona']
    success_url = reverse_lazy('warehouse')
    titulo = 'Nueva estantería'

    def get_initial(self):
        return {'zona': self.request.GET.get('zona')}


class ShelfUpdate(Formulario, UpdateView):
    model = Estanteria
    fields = ['nombre', 'zona']
    success_url = reverse_lazy('warehouse')
    titulo = 'Editar estantería'


class ShelfDelete(Borrar):
    model = Estanteria
    success_url = reverse_lazy('warehouse')
    aviso = 'Sus productos pasarán a «Sin ubicar». No se borra ningún producto.'


class Mover(Formulario, FormView):
    """Modal de mover: la URL trae 'producto' (se elige destino) o 'estanteria' (se elige producto)."""
    form_class = MoverForm
    success_url = reverse_lazy('warehouse')
    success_message = 'Producto movido.'
    mover = True  # _form_body lo marca con data-mover: almacen.js lo envía por JSON en la página del almacén

    @cached_property
    def producto(self):
        return get_object_or_404(Product, pk=self.kwargs['producto']) if 'producto' in self.kwargs else None

    @cached_property
    def estanteria(self):
        return get_object_or_404(Estanteria, pk=self.kwargs['estanteria']) if 'estanteria' in self.kwargs else None

    @property
    def titulo(self):
        return f'Mover «{self.producto.nombre}»' if self.producto else f'Añadir producto a {self.estanteria}'

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if self.producto:
            del form.fields['producto']
            form.fields['estanteria'].initial = self.producto.ubicacion_id
        else:
            del form.fields['estanteria']
            form.fields['producto'].queryset = form.fields['producto'].queryset.exclude(ubicacion=self.estanteria)
        return form

    def form_valid(self, form):
        producto = self.producto or form.cleaned_data['producto']
        destino = form.cleaned_data['estanteria'] if self.producto else self.estanteria
        Product.objects.filter(pk=producto.pk).update(ubicacion=destino)
        return super().form_valid(form)


def _id(x):
    # type(...) is int descarta bool; el tope evita desbordar el entero de SQLite
    return type(x) is int and 0 < x < 2 ** 31


class WarehouseMove(LoginRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request):
        def error(msg, status):
            return JsonResponse({'ok': False, 'error': msg}, status=status)

        try:
            datos = json.loads(request.body)
            pid, eid = datos['producto'], datos.get('estanteria')
        except (ValueError, KeyError, TypeError, AttributeError):
            return error('Petición no válida.', 400)
        if not _id(pid) or not (eid is None or _id(eid)):
            return error('Identificadores no válidos.', 400)
        producto = Product.objects.filter(pk=pid).first()
        if not producto:
            return error('El producto no existe.', 404)
        destino = None
        if eid is not None:
            destino = Estanteria.objects.select_related('zona').filter(pk=eid).first()
            if not destino:
                return error('La estantería no existe.', 404)
        Product.objects.filter(pk=pid).update(ubicacion=destino)
        return JsonResponse({
            'ok': True,
            'producto': {'id': producto.pk, 'nombre': producto.nombre},
            'estanteria': {'id': destino.pk, 'nombre': str(destino)} if destino else None,
            'contadores': contadores(),
        })


# Movimientos (solo crear y listar)
class MovementList(PaginaSegura, LoginRequiredMixin, ListView):
    model = StockMovement
    template_name = 'inventario/movement_list.html'
    paginate_by = 20

    def get_queryset(self):
        qs = StockMovement.objects.select_related('product', 'usuario')
        g = self.request.GET
        if (prod := id_filtro(g.get('producto', ''))) is not None:
            qs = qs.filter(product_id=prod)
        if g.get('tipo'):
            qs = qs.filter(tipo=g['tipo'])
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['productos'] = Product.objects.all()
        ctx['tipos'] = StockMovement.TIPOS
        query = self.request.GET.copy()
        query.pop('page', None)
        ctx['querystring'] = query.urlencode()
        return ctx


class MovementCreate(Formulario, CreateView):
    model = StockMovement
    fields = ['product', 'tipo', 'cantidad', 'nota']
    titulo = 'Registrar movimiento de stock'
    success_url = reverse_lazy('movement_list')

    def get_initial(self):
        return {'product': self.request.GET.get('product')}

    def form_valid(self, form):
        mov = form.instance
        with transaction.atomic():
            producto = Product.objects.select_for_update().get(pk=mov.product_id)
            if mov.tipo == StockMovement.SALIDA and mov.cantidad > producto.stock:
                form.add_error('cantidad', f'Stock insuficiente: disponible {producto.stock}.')
                return self.form_invalid(form)
            delta = mov.cantidad if mov.tipo == StockMovement.ENTRADA else -mov.cantidad
            Product.objects.filter(pk=producto.pk).update(stock=F('stock') + delta)
            mov.usuario = self.request.user
            mov.save()
        messages.success(self.request, 'Movimiento registrado.')
        return redirect(self.success_url)


# Importación CSV de productos
class ProductImport(LoginRequiredMixin, FormView):
    template_name = 'inventario/product_import.html'
    form_class = ProductImportForm
    success_url = reverse_lazy('product_list')

    def form_valid(self, form):
        creados, actualizados = form.importar()
        messages.success(self.request, f'Importación completada: {creados} creado(s), {actualizados} actualizado(s).')
        return super().form_valid(form)


class ProductImportTemplate(LoginRequiredMixin, View):
    def get(self, request):
        r = HttpResponse(
            '﻿nombre;sku;categoria;proveedor;precio;stock;stock_minimo\r\n'
            'Cable HDMI 2 m;ELE-100;Electrónica;TecnoMarket España;8.95;20;5\r\n'
            'Cuaderno A4;PAP-100;Papelería;Suministros Levante S.A.;2.35;40;10\r\n',
            content_type='text/csv; charset=utf-8')
        r['Content-Disposition'] = 'attachment; filename="plantilla_productos.csv"'
        return r


# Gráficos de movimientos
class MovementCharts(LoginRequiredMixin, TemplateView):
    template_name = 'inventario/movement_charts.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        try:
            dias = int(self.request.GET.get('dias', 30))
        except ValueError:
            dias = 30
        if dias not in (7, 30, 90):
            dias = 30
        hoy = timezone.localdate()
        inicio = hoy - timedelta(days=dias - 1)
        movs = StockMovement.objects.filter(fecha__date__gte=inicio)
        E, S = StockMovement.ENTRADA, StockMovement.SALIDA

        # 90 días: se agrupa por semanas (lunes) para que el gráfico sea legible
        semanal = dias == 90

        cat = movs.values('product__category__nombre').annotate(
            e=Sum('cantidad', filter=Q(tipo=E)), s=Sum('cantidad', filter=Q(tipo=S))
        ).order_by('product__category__nombre')
        bajos = Product.objects.filter(stock__lte=F('stock_minimo')).count()

        ctx['dias'] = dias
        ctx['periodos'] = (7, 30, 90)
        ctx['datos'] = {
            'semanal': semanal,
            'serie': serie_movimientos(inicio, dias, semanal),
            'categorias': {'labels': [r['product__category__nombre'] for r in cat],
                           'entradas': [r['e'] or 0 for r in cat], 'salidas': [r['s'] or 0 for r in cat]},
            'top': top_salidas(movs, 10),
            'estado': {'bajo': bajos, 'ok': Product.objects.count() - bajos},
        }
        return ctx
