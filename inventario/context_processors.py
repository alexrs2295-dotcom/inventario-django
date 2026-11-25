from django.db.models import F

from .models import Product


def alerta_stock(request):
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    # base_template: los formularios y confirmaciones devuelven solo el fragmento si la petición es AJAX (modal)
    ctx = {'es_modal': ajax, 'base_template': 'inventario/_modal_base.html' if ajax else 'base.html'}
    if ajax or not request.user.is_authenticated:
        return ctx
    sin = Product.objects.filter(stock=0)
    bajo = Product.objects.filter(stock__gt=0, stock__lte=F('stock_minimo'))
    ctx.update(
        sin_stock_n=sin.count(), sin_stock_top=list(sin[:5]),
        stock_bajo_n=bajo.count(), stock_bajo_top=list(bajo[:5]),
    )
    return ctx
