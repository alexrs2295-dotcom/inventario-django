from django.contrib import admin

from .models import Category, Estanteria, Product, StockMovement, Supplier, Zona


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    readonly_fields = ['stock']  # el stock solo cambia mediante movimientos


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    # los movimientos son un registro de trazabilidad: solo lectura
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Category)
admin.site.register(Supplier)
admin.site.register(Zona)
admin.site.register(Estanteria)
