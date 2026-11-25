/* Almacén: arrastrar y soltar fichas con Pointer Events, mover por modal, filtro y avisos.
   Arrastre: ratón/lápiz desde cualquier punto de la ficha (umbral 6 px); táctil solo desde el asa
   (touch-action: none en ella), así el scroll con el dedo fuera del asa nunca arrastra. */
(function () {
  const layout = document.querySelector('.alm-layout');
  if (!layout) return;
  const UMBRAL = 6;
  const reducido = window.matchMedia('(prefers-reduced-motion: reduce)');
  const toasts = document.getElementById('alm-toasts');
  const csrf = (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value;
  const MOVER = '/almacen/mover/';

  /* ---------- Avisos ---------- */
  function aviso(texto, error) {
    const t = document.createElement('div');
    t.className = 'alm-toast' + (error ? ' alm-toast-error' : '');
    t.textContent = texto;
    toasts.appendChild(t);
    setTimeout(function () { t.classList.add('saliendo'); setTimeout(function () { t.remove(); }, 200); }, 4000);
  }

  /* ---------- Contadores (misma función para el cálculo optimista y la respuesta del servidor) ---------- */
  function plural(n) { return n + (n === 1 ? ' producto' : ' productos'); }

  function contarDOM() {
    const c = { estanterias: {}, zonas: {}, ubicados: 0, sin_ubicar: 0 };
    layout.querySelectorAll('.estanteria').forEach(function (e) {
      const n = e.querySelectorAll('.ficha').length;
      c.estanterias[e.dataset.est] = n;
      c.ubicados += n;
    });
    layout.querySelectorAll('.zona').forEach(function (z) {
      c.zonas[z.dataset.zona] = z.querySelectorAll('.ficha').length;
    });
    c.sin_ubicar = layout.querySelectorAll('.bandeja .ficha').length;
    return c;
  }

  function pintar(c) {
    Object.keys(c.estanterias).forEach(function (id) {
      const e = document.getElementById('est-' + id);
      if (!e) return;
      const n = c.estanterias[id];
      e.querySelector('[data-n-est]').textContent = plural(n);
      e.querySelectorAll('.huecos i').forEach(function (h, i) { h.classList.toggle('lleno', i < n); });
    });
    Object.keys(c.zonas).forEach(function (id) {
      const z = layout.querySelector('.zona[data-zona="' + id + '"]');
      if (z) z.querySelector('[data-n-zona]').textContent = c.zonas[id];
    });
    document.querySelector('[data-contador="ubicados"]').textContent = c.ubicados;
    document.querySelector('[data-contador="sin_ubicar"]').textContent = c.sin_ubicar;
    document.querySelector('[data-n-bandeja]').textContent = plural(c.sin_ubicar);
  }

  /* ---------- Mover (optimista, con reversión) ---------- */
  function contenedor(estId) {
    const dz = layout.querySelector('.dropzone[data-est="' + estId + '"]');
    return dz && dz.querySelector('.items');
  }

  function insertar(items, ficha) {
    // orden alfabético, como al recargar
    const nombre = ficha.dataset.nombre;
    const antes = Array.prototype.find.call(items.children, function (f) {
      return f !== ficha && f.dataset.nombre.localeCompare(nombre, 'es') > 0;
    });
    items.insertBefore(ficha, antes || null);
  }

  function mover(ficha, estId) {
    const destino = contenedor(estId);
    const origen = ficha.parentNode, siguiente = ficha.nextSibling;
    if (!destino || destino === origen) return Promise.resolve(true);
    insertar(destino, ficha);
    ficha.classList.remove('encaja'); void ficha.offsetWidth; ficha.classList.add('encaja');
    pintar(contarDOM());
    const revertir = function (msg) {
      origen.insertBefore(ficha, siguiente);
      pintar(contarDOM());
      aviso(msg || 'No se ha podido mover «' + ficha.dataset.nombre + '». Se ha devuelto a su sitio.', true);
      return false;
    };
    return fetch(MOVER, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
      body: JSON.stringify({ producto: +ficha.dataset.id, estanteria: estId === '' ? null : +estId })
    }).then(function (r) {
      if (r.redirected) throw new Error('sesion');
      return r.json().then(function (d) { return { ok: r.ok && d.ok, d: d }; });
    }).then(function (res) {
      if (!res.ok) return revertir(res.d && res.d.error && 'No se ha podido mover: ' + res.d.error);
      pintar(res.d.contadores);
      aviso(res.d.producto.nombre + ' → ' + (res.d.estanteria ? res.d.estanteria.nombre : 'Sin ubicar'));
      return true;
    }).catch(function () { return revertir(); });
  }

  /* ---------- Arrastre ---------- */
  let pend = null, drag = null, raf = 0;

  function dzBajo(x, y) {
    const el = document.elementFromPoint(x, y);
    return el && el.closest('.dropzone');
  }

  function marcar(dz) {
    if (drag.dz === dz) return;
    if (drag.dz) drag.dz.classList.remove('activa');
    if (dz) dz.classList.add('activa');
    drag.dz = dz;
  }

  function moverClon() {
    drag.clon.style.transform = 'translate(' + (drag.x - drag.dx) + 'px,' + (drag.y - drag.dy) + 'px) rotate(2deg)';
    marcar(dzBajo(drag.x, drag.y));
  }

  function autoscroll() {
    if (!drag) return;
    const h = window.innerHeight, v = drag.y < 70 ? -14 : (drag.y > h - 70 ? 14 : 0);
    if (v) { window.scrollBy(0, v); moverClon(); }
    raf = requestAnimationFrame(autoscroll);
  }

  function empezar(e) {
    const ficha = pend.ficha, r = ficha.getBoundingClientRect();
    const clon = ficha.cloneNode(true);
    clon.removeAttribute('tabindex'); clon.setAttribute('aria-hidden', 'true');
    clon.classList.add('ficha-clon');
    clon.style.width = r.width + 'px';
    document.body.appendChild(clon);
    drag = { ficha: ficha, clon: clon, dx: pend.x - r.left, dy: pend.y - r.top, x: e.clientX, y: e.clientY, dz: null, rect: r };
    ficha.classList.add('arrastrando');
    document.body.classList.add('alm-arrastrando');
    try { ficha.setPointerCapture(pend.id); } catch (_) {}
    getSelection().removeAllRanges();
    moverClon();
    raf = requestAnimationFrame(autoscroll);
  }

  function terminar(cancelar) {
    const d = drag; pend = null;
    if (!d) return;
    drag = null;
    cancelAnimationFrame(raf);
    document.body.classList.remove('alm-arrastrando');
    if (d.dz) d.dz.classList.remove('activa');
    d.ficha.classList.remove('arrastrando');
    const destino = !cancelar && d.dz;
    if (destino && destino.dataset.est !== undefined && contenedor(destino.dataset.est) !== d.ficha.parentNode) {
      d.clon.remove();
      mover(d.ficha, destino.dataset.est);
      return;
    }
    // sin destino válido: el clon vuelve a su sitio
    const r = d.ficha.getBoundingClientRect();
    if (reducido.matches) { d.clon.remove(); return; }
    d.clon.style.transition = 'transform 0.2s var(--ease), opacity 0.2s';
    d.clon.style.transform = 'translate(' + r.left + 'px,' + r.top + 'px)';
    d.clon.style.opacity = '0';
    setTimeout(function () { d.clon.remove(); }, 220);
  }

  layout.addEventListener('pointerdown', function (e) {
    if (e.button !== 0) return;
    const ficha = e.target.closest('.ficha');
    if (!ficha || e.target.closest('.ficha-mover')) return;
    if (e.pointerType === 'touch' && !e.target.closest('.ficha-asa')) return;
    pend = { ficha: ficha, x: e.clientX, y: e.clientY, id: e.pointerId };
  });
  document.addEventListener('pointermove', function (e) {
    if (drag) { drag.x = e.clientX; drag.y = e.clientY; moverClon(); e.preventDefault(); return; }
    if (pend && e.pointerId === pend.id && Math.hypot(e.clientX - pend.x, e.clientY - pend.y) > UMBRAL) empezar(e);
  });
  document.addEventListener('pointerup', function () { if (drag) terminar(false); pend = null; });
  document.addEventListener('pointercancel', function () { terminar(true); });
  document.addEventListener('selectstart', function (e) { if (drag || pend) e.preventDefault(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && drag) terminar(true); });

  /* ---------- Teclado: Intro en la ficha abre el modal Mover ---------- */
  layout.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' || !e.target.classList.contains('ficha')) return;
    e.preventDefault();
    e.target.querySelector('.ficha-mover').click();
  });

  /* ---------- Modal Mover / Añadir producto: usa el mismo endpoint JSON ---------- */
  const content = document.getElementById('app-modal-content');
  content.addEventListener('submit', function (e) {
    const form = e.target;
    if (!form.hasAttribute('data-mover')) return;
    e.preventDefault();
    e.stopPropagation(); // evita el envío genérico de app.js
    const pid = form.dataset.producto || (form.elements.producto || {}).value;
    const est = form.dataset.estanteria !== undefined ? form.dataset.estanteria : (form.elements.estanteria || {}).value;
    const ficha = layout.querySelector('.ficha[data-id="' + pid + '"]');
    if (!ficha) { location.reload(); return; }
    // éxito o error, el modal se cierra: el resultado se ve en la ficha y en el aviso
    mover(ficha, est || '').then(function () {
      bootstrap.Modal.getInstance(document.getElementById('app-modal')).hide();
    });
  }, true);

  pintar(contarDOM()); // rellena los huecos de cada estantería al cargar

  /* ---------- Filtro rápido ---------- */
  document.getElementById('alm-buscar').addEventListener('input', function (e) {
    const q = e.target.value.trim().toLowerCase();
    layout.querySelectorAll('.ficha').forEach(function (f) {
      f.classList.toggle('atenuada', q !== '' && f.dataset.q.indexOf(q) === -1);
    });
  });
})();
