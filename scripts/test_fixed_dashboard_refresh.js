const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

function element() {
  return {textContent: '', innerHTML: '', style: {}, className: '', classList: {toggle() {}}, appendChild() {}};
}
const nodes = new Map();
const node = id => {if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id);};
const plots = new Map();
const timers = [];
let base = JSON.parse(fs.readFileSync('public/data/fixed_models_2026.json', 'utf8'));
let live = JSON.parse(fs.readFileSync('public/data/fixed_models_intraday.json', 'utf8'));
base.data_revision = 'initial';
live.base_revision = 'initial';
const script = [...fs.readFileSync('public/index.html', 'utf8').matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]).find(s => s.includes('const BASE_URL='));
vm.runInNewContext(script, {
  document: {getElementById: node, querySelector: node, createElement: element},
  Plotly: {react: (id, traces) => plots.set(id, traces)},
  setInterval: fn => timers.push(fn),
  fetch: async url => ({ok: true, json: async () => structuredClone(String(url).startsWith('data/fixed_models_intraday.json') ? live : base)}),
  console,
});

(async () => {
  for(let i=0; i<5; i++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(node('loadError').style.display, 'none');
  const old = node('returnsVc').textContent;
  base.latest.latest_sbs_date = '2026-09-02';
  base.latest.latest_sbs_vc = 71.2; // Synthetic publication used only by this test.
  base.data_revision = 'new-sbs';
  await timers[0]();
  assert.equal(node('returnsVc').textContent, old);
  assert.match(node('loadError').textContent, /Publicación en transición/);
  live.base_revision = 'new-sbs';
  live.models.retornos.vc_intraday = 71.8;
  await timers[0]();
  assert.equal(node('loadError').style.display, 'none');
  assert.equal(node('sbsVc').textContent, '71.2000');
  assert.equal(node('sbsDate').textContent, 'SBS · 02/09/2026');
  assert.equal(node('returnsVc').textContent, '71.8000');
  assert.equal(plots.get('chartVC')[2].y.at(-1), 71.8);
  for(const trace of plots.get('chartVC')) assert.equal(new Set(trace.x).size, trace.x.length);
  console.log('OK: SBS, tarjetas y gráficos se renuevan juntos sin recargar ni mezclar versiones');
})().catch(error => {console.error(error); process.exitCode=1;});
