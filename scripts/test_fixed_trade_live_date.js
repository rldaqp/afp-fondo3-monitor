const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

class FakeClassList {
  constructor(names = []) { this.names = new Set(names); }
  contains(name) { return this.names.has(name); }
  toggle(name, force) {
    const enabled = force === undefined ? !this.names.has(name) : Boolean(force);
    if (enabled) this.names.add(name); else this.names.delete(name);
    return enabled;
  }
}

class FakeElement {
  constructor({value = '', classes = [], dataset = {}} = {}) {
    this.value = value;
    this.dataset = dataset;
    this.classList = new FakeClassList(classes);
    this.className = '';
    this.textContent = '';
    this.innerHTML = '';
    this.min = '';
    this.max = '';
    this.onclick = null;
  }
  querySelectorAll() { return []; }
}

const elements = {};
for (const id of [
  'fixedTradeStyles', 'fixedTradePanel', 'tradeForm', 'tradeExitWrap',
  'tradeDetail', 'tradeDataStatus', 'tradeCalc', 'tradeSave', 'tradeCloudConnect',
  'tradeCloudUrl', 'tradeCloudKey', 'tradeEntry', 'tradeExit',
  'tradeMCap', 'tradeMFinal', 'tradeMGain', 'tradeMRet', 'tradeBody',
  'tradeCount', 'tradeCloudStatus', 'tradeCloudBadge'
]) elements[id] = new FakeElement();
elements.tradeModel = new FakeElement({value: 'retornos'});
elements.tradeCapital = new FakeElement({value: '25000'});

const modeButtons = [
  new FakeElement({classes: ['active'], dataset: {trademode: 'monitor'}}),
  new FakeElement({dataset: {trademode: 'inside'}}),
  new FakeElement({dataset: {trademode: 'closed'}}),
];

const storage = new Map();
const intervals = [];
const baseFixture = {
  rows: [
    {fecha: '2026-09-01', vc_sbs: 71.8, vc_niveles: 71.1, vc_retornos: 71.9},
    {fecha: '2026-09-02', vc_sbs: null, vc_niveles: 71.6637183631, vc_retornos: 72.0314840187},
  ],
};
let liveFixture = {
  signal_date: '2026-09-03',
  market_open: false,
  tickers: ['SPY', 'EEM', 'MCHI', 'QQQ', 'SPBLSCUP'].map(ticker => ({
    ticker,
    timestamp: ticker === 'SPBLSCUP' ? '2026-09-02' : '2026-09-03',
    fresh: ticker !== 'SPBLSCUP',
  })),
  models: {
    niveles: {vc_intraday: 71.9792739225},
    retornos: {vc_intraday: 72.4213639758},
  },
};

const document = {
  readyState: 'complete',
  getElementById: id => elements[id] || null,
  querySelectorAll: selector => selector === '[data-trademode]' ? modeButtons : [],
  querySelector: selector => selector === '[data-trademode].active'
    ? modeButtons.find(button => button.classList.contains('active')) || null
    : null,
};
const localStorage = {
  getItem: key => storage.has(key) ? storage.get(key) : null,
  setItem: (key, value) => storage.set(key, String(value)),
};
const fetch = async url => ({
  ok: true,
  status: 200,
  json: async () => structuredClone(String(url).startsWith('data/fixed_models_intraday.json') ? liveFixture : baseFixture),
});

const context = {
  console,
  document,
  localStorage,
  fetch,
  window: {addEventListener() {}, dispatchEvent() {}},
  setInterval: fn => { intervals.push(fn); return intervals.length; },
  setTimeout: () => 0,
  clearTimeout() {},
  confirm: () => false,
  Event: class Event {},
  URL,
  Intl,
  structuredClone,
};
vm.runInNewContext(fs.readFileSync('public/data/fixed_trade_runtime_v1.js', 'utf8'), context);

async function settle() {
  for (let i = 0; i < 4; i += 1) await new Promise(resolve => setImmediate(resolve));
}

(async () => {
  await settle();
  assert.equal(elements.tradeEntry.max, '2026-09-03');
  assert.equal(elements.tradeEntry.value, '2026-09-03');
  assert.equal(elements.tradeExit.max, '2026-09-03');

  modeButtons[1].onclick();
  elements.tradeCalc.onclick();
  assert.equal(elements.tradeMFinal.textContent, new Intl.NumberFormat('es-PE', {style: 'currency', currency: 'PEN'}).format(25000));
  assert.match(elements.tradeDetail.innerHTML, /03\/09\/2026/);
  assert.match(elements.tradeDetail.innerHTML, /72\.4213640/);
  assert.match(elements.tradeDetail.innerHTML, /CIERRE PROVISIONAL · 4\/5 FACTORES · SBS PENDIENTE/);
  assert.match(elements.tradeDataStatus.textContent, /CÁLCULO PROVISIONAL/);
  assert.match(elements.tradeDataStatus.textContent, /Pendientes: SPBLSCUP/);

  elements.tradeModel.value = 'niveles';
  elements.tradeCalc.onclick();
  assert.match(elements.tradeDetail.innerHTML, /71\.9792739/);

  modeButtons[2].onclick();
  elements.tradeEntry.value = '2026-09-02';
  elements.tradeExit.value = '2026-09-03';
  elements.tradeModel.value = 'retornos';
  elements.tradeCalc.onclick();
  const expectedFinal = 25000 * liveFixture.models.retornos.vc_intraday / baseFixture.rows[1].vc_retornos;
  assert.equal(elements.tradeMFinal.textContent, new Intl.NumberFormat('es-PE', {style: 'currency', currency: 'PEN'}).format(expectedFinal));
  assert.match(elements.tradeDetail.innerHTML, /Salida 03\/09\/2026/);
  elements.tradeSave.onclick();
  const saved = JSON.parse(storage.get('profuturo_fondo3_trade_history_v3'));
  assert.equal(saved.length, 1);
  assert.equal(saved[0].exit_date, '2026-09-03');
  assert.equal(saved[0].exit_est_vc, liveFixture.models.retornos.vc_intraday);
  assert.equal(saved[0].exit_sbs_vc, null);
  assert.equal(saved[0].entry_date, '2026-09-02');

  liveFixture = {
    ...liveFixture,
    signal_date: '2026-09-04',
    tickers: liveFixture.tickers.map(ticker => ({...ticker, timestamp: '2026-09-04', fresh: true})),
    models: {
      niveles: {vc_intraday: 72.1},
      retornos: {vc_intraday: 72.6},
    },
  };
  assert.equal(intervals.length, 2);
  await intervals[1]();
  assert.equal(elements.tradeEntry.max, '2026-09-04');
  assert.equal(elements.tradeEntry.value, '2026-09-02');
  assert.equal(elements.tradeExit.value, '2026-09-04');
  assert.match(elements.tradeDataStatus.textContent, /factores actualizados 5\/5/);
  assert.doesNotMatch(elements.tradeDataStatus.textContent, /Pendientes: SPBLSCUP/);

  console.log('OK: cierre vivo disponible y calculable en ambos modelos');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
