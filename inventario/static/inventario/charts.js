/* Ayudantes ECharts neo-brutalistas compartidos (portada y gráficos de movimientos). Requiere echarts. */
window.InvCharts = (function () {
  const C = { entrada: '#393F4B', salida: '#910029', ambar: '#E9B44C', verde: '#8FBF9F', hielo: '#ECF4F7', ink: '#14171C' };
  const MUTED = '#4A5361', LINE = 'rgba(20,23,28,0.22)', FONT = '"Barlow", system-ui, sans-serif';
  const charts = [];
  const tip = function (extra) {
    return Object.assign({ backgroundColor: '#fff', borderColor: C.ink, borderWidth: 2, padding: [8, 12],
      textStyle: { color: C.ink, fontSize: 14, fontWeight: 600 }, extraCssText: 'box-shadow:4px 4px 0 #14171C;border-radius:0;' }, extra);
  };
  const leyenda = function (extra) {
    return Object.assign({ top: 0, left: 0, textStyle: { color: C.ink, fontWeight: 600, fontSize: 14 }, icon: 'rect', itemWidth: 14, itemHeight: 14,
      itemStyle: { borderColor: C.ink, borderWidth: 2 } }, extra);
  };
  const eje = function (extra) {
    return Object.assign({ axisLine: { lineStyle: { color: C.ink, width: 2 } }, axisTick: { show: false }, axisLabel: { color: MUTED, fontWeight: 600 } }, extra);
  };
  const valores = function () {
    return eje({ type: 'value', minInterval: 1, axisLine: { show: false }, splitLine: { lineStyle: { color: LINE } } });
  };
  const rejilla = function (extra) {
    return Object.assign({ left: 8, right: 12, top: 36, bottom: 8, containLabel: true }, extra);
  };
  const barras = function (nombre, color, datos, extra) {
    return Object.assign({ name: nombre, type: 'bar', data: datos, itemStyle: { color: color, borderColor: C.ink, borderWidth: 2, borderRadius: 0 }, barMaxWidth: 28 }, extra);
  };
  const suma = function (a) { return a.reduce(function (x, y) { return x + y; }, 0); };
  const pintar = function (id, hay, opcion, vacio) {
    const el = document.getElementById(id);
    if (!hay) { el.innerHTML = '<p class="vacio text-secondary mb-0">' + (vacio || 'Sin datos') + '</p>'; return; }
    const c = echarts.init(el);
    c.setOption(Object.assign({ textStyle: { fontFamily: FONT, color: C.ink }, animation: false }, opcion));
    charts.push(c);
  };
  window.addEventListener('resize', function () { charts.forEach(function (c) { c.resize(); }); });
  return { C: C, tip: tip, leyenda: leyenda, eje: eje, valores: valores, rejilla: rejilla, barras: barras, suma: suma, pintar: pintar, MUTED: MUTED };
})();
