/* Modales: los enlaces con data-modal abren su href (fragmento HTML) en #app-modal.
   Sin JS siguen siendo enlaces normales a páginas completas. */
(function () {
  const el = document.getElementById('app-modal');
  if (!el || !window.bootstrap) return;
  const content = document.getElementById('app-modal-content');
  const modal = bootstrap.Modal.getOrCreateInstance(el);
  let opener = null;
  const HEADERS = { 'X-Requested-With': 'XMLHttpRequest' };

  function enfocar() {
    const error = content.querySelector('.text-danger');
    const campo = (error && error.parentElement.querySelector('input, select, textarea')) ||
      content.querySelector('input:not([type="hidden"]):not([type="radio"]), select, textarea');
    if (campo) campo.focus();
  }

  function mostrar(html) {
    content.innerHTML = html;
    if (el.classList.contains('show')) enfocar(); else modal.show();
  }

  function abrir(url) {
    fetch(url, { headers: HEADERS, credentials: 'same-origin' })
      .then(function (r) {
        // redirección (p. ej. sesión caducada) o error: se muestra la página normal
        if (r.redirected || !r.ok) { location.href = url; return null; }
        return r.text();
      })
      .then(function (html) { if (html !== null) mostrar(html); })
      .catch(function () { location.href = url; });
  }

  document.addEventListener('click', function (e) {
    const a = e.target.closest('a[data-modal]');
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    opener = a;
    abrir(a.href);
  });

  content.addEventListener('submit', function (e) {
    const form = e.target;
    if (form.method.toLowerCase() !== 'post') return;
    e.preventDefault();
    const botones = form.querySelectorAll('button[type="submit"]');
    botones.forEach(function (b) { b.disabled = true; });
    function avisar(texto) {
      form.querySelectorAll('.alert-envio').forEach(function (a) { a.remove(); });
      const aviso = document.createElement('div');
      aviso.className = 'alert alert-danger alert-envio';
      aviso.textContent = texto;
      form.prepend(aviso);
      botones.forEach(function (b) { b.disabled = false; });
    }
    // redirect manual: no se sigue la redirección para no consumir los mensajes de Django
    fetch(form.action, { method: 'POST', body: new FormData(form), headers: HEADERS, credentials: 'same-origin', redirect: 'manual' })
      .then(function (r) {
        if (r.type === 'opaqueredirect') { modal.hide(); location.reload(); return null; }
        return r.text().then(function (html) {
          if (r.ok) { mostrar(html); return; }
          avisar('No se ha podido guardar (error ' + r.status + '). Recarga la página e inténtalo de nuevo.');
        });
      })
      // no se reenvía con form.submit(): el servidor puede haber procesado ya la petición (duplicaría el movimiento)
      .catch(function () { avisar('No se ha podido guardar (error de red). Comprueba que no se haya registrado y vuelve a intentarlo.'); });
  });

  el.addEventListener('shown.bs.modal', enfocar);
  el.addEventListener('hidden.bs.modal', function () {
    content.innerHTML = '';
    if (opener && document.contains(opener)) opener.focus();
    opener = null;
  });
})();
