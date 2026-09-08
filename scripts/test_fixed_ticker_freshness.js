const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

class FakeClassList {
  constructor() { this.names = new Set(); }
  add(name) { this.names.add(name); }
  remove(name) { this.names.delete(name); }
  contains(name) { return this.names.has(name); }
  toggle(name, force) {
    const enabled = force === undefined ? !this.names.has(name) : Boolean(force);
    if (enabled) this.names.add(name); else this.names.delete(name);
    return enabled;
  }
}

function element() {
  return {
    id: '',
    textContent: '',
    title: '',
    className: '',
    classList: new FakeClassList(),
    appendChild() {},
  };
}

const source = fs.readFileSync('public/data/fixed_ticker_freshness_v1.js', 'utf8');

async function renderAt(nowIso, overrides = {}) {
  const now = new Date(nowIso);
  class FakeDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now.getTime(); }
  }

  const nodes = new Map();
  for (const id of ['updated', 'marketStamp', 'marketDate', 'marketMode', 'factorStatus', 'tickerFreshnessWarn']) {
    nodes.set(id, element());
  }
  const timers = [];
  const live = {
    generated_at_ny: nowIso,
    signal_date: '2026-09-08',
    market_open: true,
    mode: 'INTRADÍA',
    close_consolidated: false,
    fresh_factors: 5,
    total_factors: 5,
    session_open_ny: '2026-09-08T09:30:00-04:00',
    session_close_ny: '2026-09-08T16:00:00-04:00',
    next_session_open_ny: '2026-09-09T09:30:00-04:00',
    next_session_close_ny: '2026-09-09T16:00:00-04:00',
    tickers: ['SPY', 'EEM', 'MCHI', 'QQQ', 'SPBLSCUP'].map(ticker => ({
      ticker,
      timestamp: '2026-09-08',
      fresh: true,
      close_confirmed: false,
    })),
    ...overrides,
  };
  const context = {
    Date: FakeDate,
    Intl,
    console,
    fetch: async () => ({ok: true, json: async () => structuredClone(live)}),
    document: {
      head: {appendChild() {}},
      createElement: element,
      getElementById: id => nodes.get(id) || null,
      querySelector: () => null,
      querySelectorAll: () => [],
    },
    window: {addEventListener() {}},
    setTimeout: fn => { timers.push(fn); return timers.length; },
    setInterval() { return 0; },
    structuredClone,
  };
  vm.runInNewContext(source, context);
  await timers[0]();
  return nodes;
}

(async () => {
  const open = await renderAt('2026-09-08T09:54:00-04:00');
  assert.equal(open.get('marketMode').textContent, 'MERCADO ABIERTO · DATOS INTRADÍA');
  assert.match(open.get('factorStatus').textContent, /^INTRADÍA · 08\/09\/2026 · 5\/5 actualizados$/);
  assert.equal(open.get('tickerFreshnessWarn').classList.contains('show'), false);

  const pending = await renderAt('2026-09-08T16:05:00-04:00', {market_open: false});
  assert.equal(pending.get('marketMode').textContent, 'MERCADO CERRADO · CIERRE PENDIENTE');
  assert.match(pending.get('factorStatus').textContent, /^CIERRE PENDIENTE · 5\/5 verificados$/);
  assert.equal(pending.get('tickerFreshnessWarn').classList.contains('show'), true);

  console.log('OK: intradía abierto no se confunde con cierre pendiente');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
