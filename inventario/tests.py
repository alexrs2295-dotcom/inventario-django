import json
from decimal import Decimal
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from .models import Category, Estanteria, Product, StockMovement, Supplier, Zona


class InventarioTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('tester', password='x')
        self.client.force_login(self.user)
        self.cat = Category.objects.create(nombre='Cables')
        self.sup = Supplier.objects.create(nombre='Acme')
        self.p = Product.objects.create(
            nombre='Cable USB', sku='USB1', category=self.cat, supplier=self.sup, precio='3.50', stock=10)

    def mover(self, tipo, cantidad):
        return self.client.post(reverse('movement_create'), {
            'product': self.p.pk, 'tipo': tipo, 'cantidad': cantidad, 'nota': ''})

    def test_entrada_suma_stock(self):
        self.mover('ENTRADA', 5)
        self.p.refresh_from_db()
        self.assertEqual(self.p.stock, 15)
        self.assertEqual(StockMovement.objects.get().usuario, self.user)

    def test_salida_resta_stock(self):
        self.mover('SALIDA', 4)
        self.p.refresh_from_db()
        self.assertEqual(self.p.stock, 6)

    def test_salida_mayor_que_stock_es_rechazada(self):
        r = self.mover('SALIDA', 11)
        self.assertEqual(r.status_code, 200)
        self.assertIn('cantidad', r.context['form'].errors)
        self.p.refresh_from_db()
        self.assertEqual(self.p.stock, 10)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_filtros_proveedor_y_categoria(self):
        otra_cat = Category.objects.create(nombre='Pilas')
        otro_sup = Supplier.objects.create(nombre='Otro')
        otro = Product.objects.create(
            nombre='Pila AA', sku='AA1', category=otra_cat, supplier=otro_sup, precio='1')
        url = reverse('product_list')
        r = self.client.get(url, {'proveedor': otro_sup.pk})
        self.assertEqual(list(r.context['object_list']), [otro])
        r = self.client.get(url, {'categoria': self.cat.pk})
        self.assertEqual(list(r.context['object_list']), [self.p])

    def test_producto_bajo_minimo_en_alerta(self):
        Product.objects.create(
            nombre='Pila AA', sku='AA1', category=self.cat, supplier=self.sup, precio='1', stock=3)
        r = self.client.get(reverse('home'))
        self.assertContains(r, 'Stock bajo: 1 producto')
        self.assertNotContains(r, 'Sin stock:')

    def test_aviso_sin_stock_separado(self):
        Product.objects.create(nombre='Pila AA', sku='AA1', category=self.cat, supplier=self.sup, precio='1', stock=0)
        r = self.client.get(reverse('home'))
        self.assertContains(r, 'Sin stock: 1 producto')
        self.assertNotContains(r, 'Stock bajo:')

    def test_estado_stock(self):
        mk = lambda stock, minimo: Product(stock=stock, stock_minimo=minimo)
        self.assertEqual(mk(0, 5).estado_stock, 'sin')
        self.assertEqual(mk(0, 0).estado_stock, 'sin')
        self.assertEqual(mk(3, 5).estado_stock, 'bajo')
        self.assertEqual(mk(5, 5).estado_stock, 'bajo')
        self.assertEqual(mk(6, 5).estado_stock, 'ok')

    def test_stock_pct(self):
        mk = lambda stock, minimo: Product(stock=stock, stock_minimo=minimo)
        self.assertEqual(mk(0, 5).stock_pct, 0)
        self.assertEqual(mk(5, 5).stock_pct, 33.3)
        self.assertEqual(mk(15, 5).stock_pct, 100)
        self.assertEqual(mk(99, 5).stock_pct, 100)
        self.assertEqual(mk(4, 0).stock_pct, 100)

    def test_filtro_estado(self):
        sin = Product.objects.create(nombre='A', sku='A', category=self.cat, supplier=self.sup, precio='1', stock=0)
        bajo = Product.objects.create(nombre='B', sku='B', category=self.cat, supplier=self.sup, precio='1', stock=2)
        url = reverse('product_list')
        for estado, esperado in (('sin', [sin]), ('bajo', [bajo]), ('ok', [self.p])):
            r = self.client.get(url, {'estado': estado})
            self.assertEqual(list(r.context['object_list']), esperado, estado)
        self.assertEqual(len(self.client.get(url).context['object_list']), 3)

    def test_modal_devuelve_fragmento(self):
        url = reverse('product_create')
        r = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, '<html')
        self.assertNotContains(r, 'sidebar')
        self.assertContains(r, 'modal-title')
        r = self.client.get(url)
        self.assertContains(r, '<html')
        self.assertContains(r, 'sidebar')

    def test_modal_error_de_validacion_devuelve_fragmento(self):
        r = self.client.post(reverse('product_create'), {'nombre': ''}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, '<html')
        self.assertContains(r, 'text-danger')

class ImportarCSVTests(TestCase):
    CAB = 'nombre,sku,categoria,proveedor,precio,stock,stock_minimo\n'

    def setUp(self):
        self.client.force_login(User.objects.create_user('tester', password='x'))
        self.cat = Category.objects.create(nombre='Cables')
        self.sup = Supplier.objects.create(nombre='Acme')
        self.p = Product.objects.create(
            nombre='Cable USB', sku='USB1', category=self.cat, supplier=self.sup, precio='3.50', stock=10)

    def subir(self, contenido):
        if isinstance(contenido, str):
            contenido = contenido.encode('utf-8')
        return self.client.post(reverse('product_import'), {'archivo': SimpleUploadedFile('p.csv', contenido)})

    def test_crea_y_actualiza_sin_tocar_stock(self):
        r = self.subir(self.CAB + 'Cable USB-C,USB1,Cables,Acme,4.25,999,7\nPila AA,AA1,Pilas,Nuevo Prov,1.10,50,5\n')
        self.assertRedirects(r, reverse('product_list'))
        self.p.refresh_from_db()
        self.assertEqual((self.p.nombre, str(self.p.precio), self.p.stock, self.p.stock_minimo),
                         ('Cable USB-C', '4.25', 10, 7))
        nuevo = Product.objects.get(sku='AA1')
        self.assertEqual((nuevo.stock, nuevo.category.nombre, nuevo.supplier.nombre), (50, 'Pilas', 'Nuevo Prov'))
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(Product.objects.count(), 2)

    def test_fila_invalida_no_importa_nada(self):
        r = self.subir(self.CAB + 'Pila AA,AA1,Pilas,Prov,1.10,50,5\nMala,M1,Pilas,Prov,abc,5,5\nOtra,M2,Pilas,Prov,2,-1,5\n')
        self.assertEqual(r.status_code, 200)
        errores = ' '.join(r.context['form'].errors['archivo'])
        self.assertIn('Fila 3', errores)
        self.assertIn('Fila 4', errores)
        self.assertNotIn('Fila 2', errores)
        self.assertEqual(Product.objects.count(), 1)
        self.assertFalse(Category.objects.filter(nombre='Pilas').exists())

    def test_sku_duplicado_en_archivo(self):
        r = self.subir(self.CAB + 'A,X1,C,P,1,1,1\nB,X1,C,P,1,1,1\n')
        self.assertIn('duplicado', ' '.join(r.context['form'].errors['archivo']))
        self.assertEqual(Product.objects.count(), 1)

    def test_punto_y_coma_y_bom(self):
        self.subir('﻿' + self.CAB.replace(',', ';') + 'Pila AA;AA1;Pilas;Prov;1,10;50;5\n')
        self.assertEqual(str(Product.objects.get(sku='AA1').precio), '1.10')

    def test_cabecera_incorrecta(self):
        r = self.subir('nombre,sku\nA,B\n')
        self.assertIn('Cabecera incorrecta', r.context['form'].errors['archivo'][0])

    def test_plantilla_login_e_importable(self):
        r = self.client.get(reverse('product_import_template'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('text/csv', r['Content-Type'])
        self.assertEqual(self.client.get(reverse('product_import')).status_code, 200)
        self.subir(r.content)
        self.assertEqual(Product.objects.count(), 3)
        self.client.logout()
        for n in ('product_import', 'product_import_template'):
            self.assertEqual(self.client.get(reverse(n)).status_code, 302)

    def test_fila_vacia_final_y_categoria_otra_capitalizacion(self):
        r = self.subir(self.CAB + 'Pila AA,AA1,cables,Acme,1.10,50,5\n,,,,,,\n')
        self.assertRedirects(r, reverse('product_list'))
        self.assertEqual(Category.objects.count(), 1)
        self.assertEqual(Product.objects.get(sku='AA1').category, self.cat)

    def test_solo_filas_vacias_es_error(self):
        r = self.subir(self.CAB + ',,,,,,\n')
        self.assertEqual(r.status_code, 200)
        self.assertIn('archivo', r.context['form'].errors)

    def test_csv_corrupto_no_da_500(self):
        r = self.subir('\ufeffnombre,sku\n"abc')
        self.assertEqual(r.status_code, 200)
        r = self.subir('nombre\x00,sku\n1,2\n')
        self.assertEqual(r.status_code, 200)
        self.assertIn('archivo', r.context['form'].errors)


class GraficosTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('tester', password='x')
        self.client.force_login(self.user)
        self.url = reverse('movement_charts')

    def test_sin_datos(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['datos']['top']['labels'], [])

    def test_con_datos(self):
        cat = Category.objects.create(nombre='Cables')
        p = Product.objects.create(nombre='Cable', sku='C1', category=cat,
                                   supplier=Supplier.objects.create(nombre='Acme'), precio='1', stock=2)
        StockMovement.objects.create(product=p, tipo='ENTRADA', cantidad=5, usuario=self.user)
        StockMovement.objects.create(product=p, tipo='SALIDA', cantidad=3, usuario=self.user)
        r = self.client.get(self.url, {'dias': 90})
        d = r.context['datos']
        self.assertEqual(r.status_code, 200)
        self.assertEqual((sum(d['serie']['entradas']), sum(d['serie']['salidas'])), (5, 3))
        self.assertEqual(d['top'], {'labels': ['Cable'], 'valores': [3]})
        self.assertEqual(d['estado'], {'bajo': 1, 'ok': 0})

    def test_dias_validado(self):
        for valor, esperado in (('7', 7), ('90', 90), ('5', 30), ('abc', 30), ('', 30)):
            r = self.client.get(self.url, {'dias': valor})
            self.assertEqual((r.status_code, r.context['dias']), (200, esperado))

    def test_sin_login_redirige(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)


class AlmacenTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('tester', password='x'))
        cat = Category.objects.create(nombre='Cables')
        sup = Supplier.objects.create(nombre='Acme')
        self.zona = Zona.objects.create(nombre='Pasillo A')
        self.e1 = Estanteria.objects.create(zona=self.zona, nombre='Estantería 1')
        self.e2 = Estanteria.objects.create(zona=self.zona, nombre='Estantería 2')
        self.p = Product.objects.create(nombre='Cable USB', sku='USB1', category=cat, supplier=sup,
                                        precio='3.50', stock=10, ubicacion=self.e1)
        self.libre = Product.objects.create(nombre='Pila AA', sku='AA1', category=cat, supplier=sup, precio='1')
        self.url = reverse('warehouse_move')

    def mover(self, datos, **kw):
        return self.client.post(self.url, json.dumps(datos), content_type='application/json', **kw)

    def test_mover_actualiza_ubicacion_y_devuelve_contadores(self):
        r = self.mover({'producto': self.libre.pk, 'estanteria': self.e2.pk})
        self.assertEqual(r.status_code, 200)
        self.libre.refresh_from_db()
        self.assertEqual(self.libre.ubicacion, self.e2)
        d = r.json()
        self.assertTrue(d['ok'])
        self.assertEqual(d['estanteria'], {'id': self.e2.pk, 'nombre': 'Pasillo A · Estantería 2'})
        c = d['contadores']
        self.assertEqual(c['estanterias'], {str(self.e1.pk): 1, str(self.e2.pk): 1})
        self.assertEqual((c['zonas'][str(self.zona.pk)], c['ubicados'], c['sin_ubicar']), (2, 2, 0))

    def test_mover_a_null(self):
        r = self.mover({'producto': self.p.pk, 'estanteria': None})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()['estanteria'])
        self.p.refresh_from_db()
        self.assertIsNone(self.p.ubicacion)
        self.assertEqual(r.json()['contadores']['sin_ubicar'], 2)

    def test_ids_invalidos_o_inexistentes(self):
        for datos, estado in (
                ({'producto': 'x'}, 400), ({'producto': True}, 400), ({'producto': self.p.pk, 'estanteria': '1'}, 400),
                ({'producto': 10 ** 30}, 400), ({'producto': -1}, 400), ({}, 400), ([1], 400),
                ({'producto': 999999}, 404), ({'producto': self.p.pk, 'estanteria': 999999}, 404)):
            self.assertEqual(self.mover(datos).status_code, estado, datos)
        r = self.client.post(self.url, 'no es json', content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.p.refresh_from_db()
        self.assertEqual(self.p.ubicacion, self.e1)

    def test_login_y_metodo(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.mover({'producto': self.p.pk, 'estanteria': None}).status_code, 302)
        self.assertEqual(self.client.get(reverse('warehouse')).status_code, 302)
        self.p.refresh_from_db()
        self.assertEqual(self.p.ubicacion, self.e1)

    def test_pagina_con_y_sin_datos(self):
        r = self.client.get(reverse('warehouse'))
        self.assertContains(r, 'Pasillo A')
        self.assertContains(r, 'Cable USB')
        self.assertContains(r, f'id="est-{self.e1.pk}"')
        Zona.objects.all().delete()
        Product.objects.update(ubicacion=None)
        r = self.client.get(reverse('warehouse'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Crear la primera zona')

    def test_crud_zona(self):
        r = self.client.post(reverse('zone_create'), {'nombre': 'Zona frío'})
        self.assertRedirects(r, reverse('warehouse'))
        z = Zona.objects.get(nombre='Zona frío')
        self.client.post(reverse('zone_update', args=[z.pk]), {'nombre': 'Cámara'})
        z.refresh_from_db()
        self.assertEqual(z.nombre, 'Cámara')
        r = self.client.post(reverse('zone_create'), {'nombre': 'Cámara'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('nombre', r.context['form'].errors)

    def test_eliminar_zona_deja_productos_sin_ubicar(self):
        r = self.client.get(reverse('zone_delete', args=[self.zona.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(r, 'pasarán a «Sin ubicar»')
        self.client.post(reverse('zone_delete', args=[self.zona.pk]))
        self.assertEqual((Zona.objects.count(), Estanteria.objects.count()), (0, 0))
        self.p.refresh_from_db()
        self.assertIsNone(self.p.ubicacion)
        self.assertEqual(Product.objects.count(), 2)

    def test_crud_estanteria(self):
        r = self.client.post(reverse('shelf_create'), {'nombre': 'Estantería 3', 'zona': self.zona.pk})
        self.assertRedirects(r, reverse('warehouse'))
        e = Estanteria.objects.get(nombre='Estantería 3')
        self.client.post(reverse('shelf_update', args=[e.pk]), {'nombre': 'Alta', 'zona': self.zona.pk})
        e.refresh_from_db()
        self.assertEqual(str(e), 'Pasillo A · Alta')
        r = self.client.get(reverse('shelf_create'), {'zona': self.zona.pk})
        self.assertEqual(r.context['form'].initial['zona'], str(self.zona.pk))

    def test_estanteria_unica_por_zona(self):
        r = self.client.post(reverse('shelf_create'), {'nombre': 'Estantería 1', 'zona': self.zona.pk})
        self.assertEqual(r.status_code, 200)
        self.assertIn('Ya existe', str(r.context['form'].errors['nombre']))
        otra = Zona.objects.create(nombre='Pasillo B')
        Estanteria.objects.create(zona=otra, nombre='Estantería 1')  # mismo nombre en otra zona: permitido
        with self.assertRaises(IntegrityError), transaction.atomic():
            Estanteria.objects.create(zona=self.zona, nombre='Estantería 1')

    def test_eliminar_estanteria_deja_productos_sin_ubicar(self):
        self.client.post(reverse('shelf_delete', args=[self.e1.pk]))
        self.p.refresh_from_db()
        self.assertIsNone(self.p.ubicacion)
        self.assertEqual(Estanteria.objects.count(), 1)

    def test_modal_mover_y_anadir_producto(self):
        r = self.client.get(reverse('product_move', args=[self.p.pk]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertContains(r, '<optgroup label="Pasillo A">')
        self.assertContains(r, 'data-mover')
        self.client.post(reverse('product_move', args=[self.p.pk]), {'estanteria': self.e2.pk})
        self.p.refresh_from_db()
        self.assertEqual(self.p.ubicacion, self.e2)
        r = self.client.get(reverse('shelf_add_product', args=[self.e2.pk]))
        self.assertContains(r, 'Pila AA (AA1) · ahora en: Sin ubicar')
        self.assertNotContains(r, 'Cable USB')  # ya está en esta estantería
        self.client.post(reverse('shelf_add_product', args=[self.e2.pk]), {'producto': self.libre.pk})
        self.libre.refresh_from_db()
        self.assertEqual(self.libre.ubicacion, self.e2)
        self.client.post(reverse('product_move', args=[self.p.pk]), {'estanteria': ''})
        self.p.refresh_from_db()
        self.assertIsNone(self.p.ubicacion)
        self.assertEqual(self.client.get(reverse('product_move', args=[99999])).status_code, 404)

    def test_filtro_ubicacion(self):
        url = reverse('product_list')
        for valor, esperado in ((str(self.e1.pk), [self.p]), ('sin', [self.libre]), (str(self.e2.pk), [])):
            r = self.client.get(url, {'ubicacion': valor})
            self.assertEqual(list(r.context['object_list']), esperado, valor)
        for basura in ('abc', '1; DROP', '9' * 40, '-1', ''):
            r = self.client.get(url, {'ubicacion': basura})
            self.assertEqual(r.status_code, 200, basura)
        self.assertEqual(len(self.client.get(url, {'ubicacion': 'abc'}).context['object_list']), 2)
        r = self.client.get(url, {'ubicacion': self.e1.pk, 'q': 'zzz'})  # conserva el resto de filtros
        self.assertEqual(list(r.context['object_list']), [])

    def test_chip_ubicacion_en_lista_y_detalle(self):
        for r in (self.client.get(reverse('product_list')), self.client.get(self.p.get_absolute_url())):
            self.assertContains(r, f'/almacen/#est-{self.e1.pk}')
        self.assertContains(self.client.get(self.libre.get_absolute_url()), 'Sin ubicar')

    def test_formulario_producto_guarda_ubicacion(self):
        datos = {'nombre': 'Nuevo', 'sku': 'N1', 'category': self.p.category_id, 'supplier': self.p.supplier_id,
                 'precio': '2', 'stock': 1, 'stock_minimo': 1, 'ubicacion': self.e2.pk}
        self.client.post(reverse('product_create'), datos)
        self.assertEqual(Product.objects.get(sku='N1').ubicacion, self.e2)
        datos.pop('stock')
        datos['ubicacion'] = ''
        self.client.post(reverse('product_update', args=[Product.objects.get(sku='N1').pk]), datos)
        self.assertIsNone(Product.objects.get(sku='N1').ubicacion)

    def test_seed_demo_dos_veces_no_duplica(self):
        User.objects.create_user('admin', password='x')
        call_command('seed_demo', stdout=StringIO())
        n = (Zona.objects.count(), Estanteria.objects.count(), Product.objects.count(), StockMovement.objects.count())
        call_command('seed_demo', stdout=StringIO())
        self.assertEqual(n, (Zona.objects.count(), Estanteria.objects.count(), Product.objects.count(),
                             StockMovement.objects.count()))
        self.assertEqual(Zona.objects.filter(nombre__in=['Pasillo A', 'Pasillo B', 'Zona frío']).count(), 3)
        self.assertTrue(Product.objects.filter(ubicacion__isnull=True).exists())
        self.assertTrue(Product.objects.filter(sku='ELE-001', ubicacion__isnull=False).exists())


class PortadaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('tester', password='x')
        self.client.force_login(self.user)
        self.url = reverse('home')

    def test_sin_login_redirige(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_sin_datos(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.context['kpi']['n'], r.context['kpi']['valor'], r.context['kpi']['movs30']), (0, 0, 0))
        self.assertEqual(r.context['datos']['top']['labels'], [])
        self.assertContains(r, 'Sin movimientos.')

    def test_kpis_y_graficos_con_datos(self):
        cat, sup = Category.objects.create(nombre='Cables'), Supplier.objects.create(nombre='Acme')
        mk = lambda sku, stock, precio='2.50': Product.objects.create(
            nombre=f'P{sku}', sku=sku, category=cat, supplier=sup, precio=precio, stock=stock, stock_minimo=5)
        ok, bajo, sin = mk('A', 10), mk('B', 3), mk('C', 0)
        StockMovement.objects.create(product=ok, tipo='ENTRADA', cantidad=5, usuario=self.user)
        StockMovement.objects.create(product=ok, tipo='SALIDA', cantidad=2, usuario=self.user)
        r = self.client.get(self.url)
        k, d = r.context['kpi'], r.context['datos']
        self.assertEqual((k['n'], k['sin'], k['bajo'], k['movs30'], k['unidades']), (3, 1, 1, 2, 13))
        self.assertEqual(k['valor'], Decimal('32.50'))
        self.assertEqual(d['estado'], {'ok': 1, 'bajo': 1, 'sin': 1})
        self.assertEqual((sum(d['serie']['entradas']), sum(d['serie']['salidas']), len(d['serie']['labels'])), (5, 2, 14))
        self.assertEqual(d['top'], {'labels': ['PA'], 'valores': [2]})
        self.assertEqual(d['categorias'], {'labels': ['Cables'], 'valores': [13]})
        self.assertContains(r, '?estado=sin')
        self.assertContains(r, 'id="g-estado"')


class AuditoriaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('tester', password='x', is_staff=True, is_superuser=True)
        self.client.force_login(self.user)
        self.cat = Category.objects.create(nombre='Cables')
        self.sup = Supplier.objects.create(nombre='Acme')
        self.p = Product.objects.create(
            nombre='Cable USB', sku='USB1', category=self.cat, supplier=self.sup, precio='3.50', stock=10)

    def mover(self, tipo, cantidad):
        return self.client.post(reverse('movement_create'), {
            'product': self.p.pk, 'tipo': tipo, 'cantidad': cantidad, 'nota': ''})

    def test_filtros_con_basura_dan_200(self):
        for url, param in ((reverse('product_list'), 'proveedor'), (reverse('product_list'), 'categoria'),
                           (reverse('movement_list'), 'producto')):
            for valor in ('abc', '9' * 40, '-1', '1.5'):
                self.assertEqual(self.client.get(url, {param: valor}).status_code, 200, (param, valor))

    def test_pagina_fuera_de_rango_o_no_numerica(self):
        StockMovement.objects.create(product=self.p, tipo='ENTRADA', cantidad=1, usuario=self.user)
        for url in (reverse('product_list'), reverse('movement_list')):
            for pagina in ('999', 'abc', '0', '-3'):
                r = self.client.get(url, {'page': pagina})
                self.assertEqual(r.status_code, 200, (url, pagina))
                self.assertEqual(r.context['page_obj'].number, 1)

    def test_salida_igual_al_stock_deja_cero(self):
        self.assertEqual(self.mover('SALIDA', 10).status_code, 302)
        self.p.refresh_from_db()
        self.assertEqual(self.p.stock, 0)

    def test_editar_producto_ignora_stock_enviado(self):
        r = self.client.post(reverse('product_update', args=[self.p.pk]), {
            'nombre': 'Cable USB 2', 'sku': 'USB1', 'category': self.cat.pk, 'supplier': self.sup.pk,
            'precio': '3.50', 'stock_minimo': 5, 'stock': 999})
        self.assertEqual(r.status_code, 302)
        self.p.refresh_from_db()
        self.assertEqual((self.p.nombre, self.p.stock), ('Cable USB 2', 10))

    def test_mover_almacen_exige_csrf(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.user)
        r = c.post(reverse('warehouse_move'), json.dumps({'producto': self.p.pk, 'estanteria': None}),
                   content_type='application/json')
        self.assertEqual(r.status_code, 403)

    def test_cantidad_enorme_rechazada(self):
        r = self.mover('ENTRADA', 2 ** 31)
        self.assertEqual(r.status_code, 200)
        self.assertIn('cantidad', r.context['form'].errors)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.p.refresh_from_db()
        self.assertEqual(self.p.stock, 10)

    def test_alta_producto_con_stock_enorme_rechazada(self):
        r = self.client.post(reverse('product_create'), {
            'nombre': 'X', 'sku': 'X1', 'category': self.cat.pk, 'supplier': self.sup.pk,
            'precio': '1', 'stock': 2 ** 31, 'stock_minimo': 2 ** 31})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.context['form'].errors), {'stock', 'stock_minimo'})

    def test_admin_movimientos_sin_permisos(self):
        m = StockMovement.objects.create(product=self.p, tipo='ENTRADA', cantidad=1, usuario=self.user)
        self.assertEqual(self.client.get(reverse('admin:inventario_stockmovement_add')).status_code, 403)
        self.assertEqual(self.client.post(reverse('admin:inventario_stockmovement_change', args=[m.pk]),
                                          {'cantidad': 5}).status_code, 403)
        self.assertEqual(self.client.post(reverse('admin:inventario_stockmovement_delete', args=[m.pk]),
                                          {'post': 'yes'}).status_code, 403)
        m.refresh_from_db()
        self.assertEqual(m.cantidad, 1)

    def test_admin_producto_stock_solo_lectura(self):
        r = self.client.get(reverse('admin:inventario_product_change', args=[self.p.pk]))
        self.assertNotIn('stock', r.context['adminform'].form.fields)

    def test_top_salidas_no_fusiona_nombres_iguales(self):
        otro = Product.objects.create(
            nombre=self.p.nombre, sku='USB2', category=self.cat, supplier=self.sup, precio='1', stock=5)
        StockMovement.objects.create(product=self.p, tipo='SALIDA', cantidad=3, usuario=self.user)
        StockMovement.objects.create(product=otro, tipo='SALIDA', cantidad=2, usuario=self.user)
        self.assertEqual(self.client.get(reverse('home')).context['datos']['top']['valores'], [3, 2])

