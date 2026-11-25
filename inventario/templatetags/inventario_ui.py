from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

_TRAY = '<path d="M4 13v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/>'
ICONOS = {
    # flecha que entra en la bandeja / flecha que sale de ella
    'entrada': '<path d="M12 3v11M8 10l4 4 4-4"/>' + _TRAY,
    'salida': '<path d="M12 15V4M8 8l4-4 4 4"/>' + _TRAY,
    'calendario': '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M8 3v4M16 3v4"/>',
    'mover': '<path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/>',
    'salir': '<path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M16 8l4 4-4 4M20 12H9"/>',
}
USUARIO = '<circle cx="12" cy="9" r="4" fill="currentColor"/><path d="M4.5 20.5c.6-4 3.6-6 7.5-6s6.9 2 7.5 6z" fill="currentColor"/>'


@register.simple_tag
def icono(nombre, size=16):
    """SVG inline decorativo; el color lo da currentColor."""
    if nombre == 'usuario':
        cuerpo, attrs = USUARIO, 'fill="none"'
    else:
        cuerpo = ICONOS[nombre]
        attrs = 'fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"'
    return format_html(
        '<svg class="icono" width="{0}" height="{0}" viewBox="0 0 24 24" {1} aria-hidden="true" focusable="false">{2}</svg>',
        size, mark_safe(attrs), mark_safe(cuerpo))


@register.simple_tag
def tipo_badge(tipo):
    clave = tipo.lower()
    return format_html('<span class="tipo-badge tipo-{}">{}<span>{}</span></span>',
                       clave, icono(clave, 16), 'Entrada' if clave == 'entrada' else 'Salida')


ESTADOS = {'sin': 'Sin stock', 'bajo': 'Stock bajo', 'ok': 'Correcto'}


@register.simple_tag
def estado_badge(producto):
    e = producto.estado_stock
    return format_html('<span class="estado-badge estado-{}">{}</span>', e, ESTADOS[e])
