from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse


MAX_INT = 2 ** 31 - 1  # tope del entero de SQLite/Django para estos campos


class Category(models.Model):
    nombre = models.CharField('nombre', max_length=100, unique=True)

    class Meta:
        verbose_name = 'categoría'
        verbose_name_plural = 'categorías'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Supplier(models.Model):
    nombre = models.CharField('nombre', max_length=150)
    email = models.EmailField('email', blank=True)
    telefono = models.CharField('teléfono', max_length=30, blank=True)

    class Meta:
        verbose_name = 'proveedor'
        verbose_name_plural = 'proveedores'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Zona(models.Model):
    """Pasillo o zona del almacén."""
    nombre = models.CharField('nombre', max_length=100, unique=True)
    orden = models.PositiveIntegerField('orden', default=0)

    class Meta:
        verbose_name = 'zona'
        verbose_name_plural = 'zonas'
        ordering = ['orden', 'nombre']

    def __str__(self):
        return self.nombre


class Estanteria(models.Model):
    nombre = models.CharField('nombre', max_length=100)
    zona = models.ForeignKey(Zona, verbose_name='zona', on_delete=models.CASCADE, related_name='estanterias')
    orden = models.PositiveIntegerField('orden', default=0)

    class Meta:
        verbose_name = 'estantería'
        verbose_name_plural = 'estanterías'
        ordering = ['orden', 'nombre']
        constraints = [models.UniqueConstraint(fields=['zona', 'nombre'], name='estanteria_unica_por_zona')]

    def __str__(self):
        return f'{self.zona.nombre} · {self.nombre}'

    def validate_constraints(self, exclude=None):
        # mensaje claro en el formulario (la constraint por defecto es genérica)
        try:
            super().validate_constraints(exclude)
        except ValidationError:
            raise ValidationError({'nombre': 'Ya existe una estantería con ese nombre en esta zona.'})


class Product(models.Model):
    nombre = models.CharField('nombre', max_length=150)
    sku = models.CharField('SKU', max_length=50, unique=True)
    category = models.ForeignKey(Category, verbose_name='categoría', on_delete=models.PROTECT)
    supplier = models.ForeignKey(Supplier, verbose_name='proveedor', on_delete=models.PROTECT)
    precio = models.DecimalField('precio', max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    stock = models.PositiveIntegerField('stock', default=0, validators=[MaxValueValidator(MAX_INT)])
    stock_minimo = models.PositiveIntegerField('stock mínimo', default=5, validators=[MaxValueValidator(MAX_INT)])
    ubicacion = models.ForeignKey(Estanteria, verbose_name='ubicación', null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name='productos')

    class Meta:
        verbose_name = 'producto'
        verbose_name_plural = 'productos'
        ordering = ['nombre']

    def __str__(self):
        return f'{self.nombre} ({self.sku})'

    def get_absolute_url(self):
        return reverse('product_detail', args=[self.pk])

    @property
    def estado_stock(self):
        if self.stock == 0:
            return 'sin'
        return 'bajo' if self.stock <= self.stock_minimo else 'ok'

    @property
    def stock_pct(self):
        """Llenado del medidor (0-100): tope = 3 veces el stock mínimo."""
        return round(min(self.stock / max(self.stock_minimo * 3, 1), 1) * 100, 1)


class StockMovement(models.Model):
    ENTRADA = 'ENTRADA'
    SALIDA = 'SALIDA'
    TIPOS = [(ENTRADA, 'Entrada'), (SALIDA, 'Salida')]

    # PROTECT: un producto con movimientos no se puede borrar (trazabilidad)
    product = models.ForeignKey(Product, verbose_name='producto', on_delete=models.PROTECT)
    tipo = models.CharField('tipo', max_length=7, choices=TIPOS)
    cantidad = models.PositiveIntegerField('cantidad', validators=[MinValueValidator(1), MaxValueValidator(MAX_INT)])
    fecha = models.DateTimeField('fecha', auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='usuario', on_delete=models.PROTECT)
    nota = models.CharField('nota', max_length=255, blank=True)

    class Meta:
        verbose_name = 'movimiento de stock'
        verbose_name_plural = 'movimientos de stock'
        ordering = ['-fecha', '-id']

    def __str__(self):
        return f'{self.get_tipo_display()} de {self.cantidad} x {self.product}'
