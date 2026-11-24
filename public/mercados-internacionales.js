(() => {
  'use strict';
  const id = name => document.getElementById(name);
  const file = 'data/indices_internacionales.json';
  const raw = 'https://raw.githubusercontent.com/rldaqp/afp-fondo3-monitor/migracion-github-actions/public/' + file;
  const clock = tz => new Intl.DateTimeFormat('es-PE', {timeZone: tz, day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit', hourCycle:'h23'});
  const lima = clock('America/Lima');
  const limaTime = new Intl.DateTimeFormat('es-PE', {timeZone:'America/Lima', hour:'2-digit', minute:'2-digit', hourCycle:'h23'});
  const dateFormats = new Map();
  const number = new Intl.NumberFormat('es-PE', {minimumFractionDigits:2, maximumFractionDigits:2});
  const change = new Intl.NumberFormat('es-PE', {minimumFractionDigits:2, maximumFractionDigits:2, signDisplay:'exceptZero'});
  const labels = {SPY:'S&P 500', QQQ:'Nasdaq 100', EEM:'Emergentes', EPU:'Perú', MCHI:'China', CPER:'Cobre'};
  let data, region = 'china', selected = '000001.SS', chartKey = '', loading = false;
  const stamp = t => lima.format(t * 1000);

  function dayIn(tz, epoch) {
    if (!dateFormats.has(tz)) dateFormats.set(tz, new Intl.DateTimeFormat('en-CA', {timeZone:tz, year:'numeric', month:'2-digit', day:'2-digit'}));
    const parts = Object.fromEntries(dateFormats.get(tz).formatToParts(epoch * 1000).map(part => [part.type,part.value]));
    return [parts.year, parts.month, parts.day].join('-');
  }
  function element(tag, value, className) {
    const node = document.createElement(tag);
    if (value != null) node.textContent = value;
    if (className) node.className = className;
    return node;
  }
  function marketState(calendar, now) {
    if (!calendar || dayIn(calendar.tz, now) > calendar.until) return {name:'Horario por confirmar', css:'', unknown:true};
    const session = calendar.sessions.filter(s => s[0] <= now).at(-1);
    if (!session) return {name:'Horario por confirmar', css:'', unknown:true};
    const [open, pause, resume, close] = session;
    if (now >= close) return {name:'Cerrado', css:'market-closed', open, close};
    if (pause && now >= pause && now < resume) return {name:'En receso', css:'market-break', open, pause};
    return {name:'En sesión', css:'market-open', open, live:true};
  }
  function quoteCells(row, quote) {
    row.append(element('td', Number.isFinite(quote?.price) ? number.format(quote.price) : '—'));
    const pct = quote?.change;
    row.append(element('td', Number.isFinite(pct) ? change.format(pct) + '%' : '—',
      pct > 0 ? 'gain' : pct < 0 ? 'loss' : ''));
  }
  function ageNote(item, state, now) {
    if (!item.ok) return 'Fuente sin actualizar';
    if (!item.quote || state.unknown) return '';
    const t = item.quote.at;
    if (t < state.open) return 'Dato de otra sesión';
    if (state.live && now - t > 30 * 60) return 'Dato demorado';
    if (state.close && t < state.close - 20 * 60) return 'Cierre pendiente';
    return '';
  }
  function drawChart(item) {
    const details = id('world-detail');
    const q = item.quote;
    id('world-summary').textContent = 'Gráfico de la sesión · ' + item.name + (q ? ' · ' + q.session.split('-').reverse().join('/') : '');
    id('world-source').href = 'https://finance.yahoo.com/quote/' + encodeURIComponent(item.symbol) + '/';
    if (!details.open) return;
    const key = [data.checked_at, item.symbol, q?.at].join('/');
    if (key === chartKey) return;
    chartKey = key;
    const host = id('world-chart');
    const points = q?.points || [];
    if (!window.Plotly || !points.length) {
      if (window.Plotly) window.Plotly.purge(host);
      host.textContent = 'Gráfico intradía sin datos disponibles.';
      return;
    }
    if (!host.querySelector('.plot-container')) host.replaceChildren();
    const x = [], y = [], hover = [];
    let last = 0;
    const cal = data.calendars[item.calendar];
    const session = cal.sessions.find(s => dayIn(cal.tz, s[0]) === q.session);
    for (const [t, price] of points) {
      if (session?.[1] && t >= session[1] && t < session[2]) continue;
      if (last && t - last > 11 * 60) { x.push(null); y.push(null); hover.push(''); }
      x.push(t); y.push(price); hover.push(stamp(t)); last = t;
    }
    const times = x.filter(t => t !== null);
    if (!times.length) { host.textContent = 'Gráfico intradía sin datos disponibles.'; return; }
    const ticks = Math.min(5, times.length);
    const tickvals = Array.from({length:ticks}, (_, i) => times[Math.round(i * (times.length - 1) / Math.max(1,ticks - 1))]);
    window.Plotly.react(host, [{
      x, y, customdata:hover, type:'scatter', mode:times.length === 1 ? 'markers' : 'lines', connectgaps:false,
      line:{color:'#62c8f6',width:2}, hovertemplate:'%{customdata} Perú<br>%{y:,.2f} pts<extra></extra>'
    }], {
      margin:{l:54,r:14,t:12,b:30}, paper_bgcolor:'transparent', plot_bgcolor:'transparent',
      font:{color:'#cbd5e1',size:11}, showlegend:false,
      xaxis:{tickvals,ticktext:tickvals.map(t => limaTime.format(t*1000)),gridcolor:'#25364a',fixedrange:true},
      yaxis:{gridcolor:'#25364a',fixedrange:true,separatethousands:true}
    }, {responsive:true,displayModeBar:false});
  }
  function renderIndices(now) {
    const items = data.indices.filter(item => item.group === region);
    if (!items.some(item => item.symbol === selected)) selected = items[0]?.symbol;
    const rows = items.map(item => {
      const tr = element('tr');
      const name = element('td'), button = element('button', item.name);
      button.type = 'button';
      button.setAttribute('aria-controls', 'world-detail');
      button.addEventListener('click', () => {
        selected = item.symbol;
        id('world-detail').open = true;
        drawChart(item);
      });
      name.append(button, element('small', item.market));
      tr.append(name);
      quoteCells(tr, item.quote);
      const status = marketState(data.calendars[item.calendar], now);
      const td = element('td');
      td.append(element('span', status.name, status.css), element('small', item.quote ? stamp(item.quote.at) : 'Sin cotización'));
      const note = ageNote(item, status, now);
      if (note) td.append(element('small', note, 'late'));
      tr.append(td);
      return tr;
    });
    id('world-rows').replaceChildren(...rows);
    if (items.length) drawChart(items.find(item => item.symbol === selected));
  }
  function renderPre(now) {
    const ny = data.calendars.XNYS;
    const today = dayIn(ny.tz, now);
    const session = ny.sessions.filter(s => dayIn(ny.tz, s[0]) <= today).at(-1);
    if (!session || today > ny.until) {
      id('pre-state').textContent = 'Horario por confirmar';
      id('pre-rows').replaceChildren();
      return;
    }
    const day = dayIn(ny.tz, session[0]), open = session[0] - 5.5 * 3600, end = session[0];
    const phase = now < open ? 'Próxima preapertura' : now < end ? 'Premercado abierto' : 'Premercado finalizado';
    id('pre-state').textContent = phase + ' · ' + stamp(open) + '–' + limaTime.format(end * 1000) + ' Perú';
    const rows = Object.entries(labels).map(([symbol, label]) => {
      const tr = element('tr'), td = element('td'), link = element('a', symbol);
      link.href = 'https://www.nasdaq.com/market-activity/etf/' + symbol.toLowerCase() + '/pre-market';
      link.target = '_blank'; link.rel = 'noopener noreferrer';
      td.append(link, element('small', label));
      tr.append(td);
      const item = data.premarket_day === day ? data.premarket[symbol] : undefined;
      const q = item?.quote;
      quoteCells(tr, q);
      const last = element('td');
      if (q) {
        last.append(element('span', stamp(q.at)), element('small', q.source));
      } else {
        const message = now < open ? 'Aún no abre' : item?.ok ? 'Sin cotización reportada' : 'Dato pendiente';
        last.append(element('small', message));
      }
      if (item && !item.ok) last.append(element('small','Fuente sin actualizar','late'));
      tr.append(last);
      return tr;
    });
    id('pre-rows').replaceChildren(...rows);
  }
  function render() {
    if (!data) return;
    const now = Math.floor(Date.now()/1000);
    id('world-check').textContent = 'Última consulta · ' + stamp(data.checked_at) + ' Perú';
    renderIndices(now);
    renderPre(now);
  }
  function valid(payload) {
    return payload && Number.isFinite(payload.checked_at) && Array.isArray(payload.indices) && payload.indices.length &&
      payload.calendars?.XNYS?.sessions?.length && payload.premarket;
  }
  async function read(url) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 14000);
    try {
      const r = await fetch(url, {cache:'no-store',signal:controller.signal});
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const payload = await r.json();
      if (!valid(payload)) throw new Error('Formato no disponible');
      if (!data || payload.checked_at > data.checked_at) { data = payload; render(); }
    } finally { clearTimeout(timeout); }
  }
  async function refresh() {
    if (loading) return;
    loading = true;
    const version = '?v=' + Math.floor(Date.now()/60000);
    const results = await Promise.allSettled([read(file + version), read(raw + version)]);
    loading = false;
    if (results.every(r => r.status === 'rejected')) {
      id('world-check').textContent = data ? 'Última consulta disponible · ' + stamp(data.checked_at) + ' Perú' : 'Índices sin datos disponibles';
      if (!data) id('pre-state').textContent = 'Datos de premercado no disponibles';
    }
  }
  id('world-detail').addEventListener('toggle', () => {
    const item = data?.indices.find(i => i.symbol === selected);
    if (item) drawChart(item);
  });
  id('world-regions').addEventListener('click', event => {
    const button = event.target.closest('button[data-region]');
    if (!button) return;
    region = button.dataset.region;
    for (const b of id('world-regions').querySelectorAll('button')) b.setAttribute('aria-pressed',String(b === button));
    render();
  });
  id('reload').addEventListener('click', refresh);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { render(); refresh(); } });
  setInterval(() => { if (!document.hidden) { render(); refresh(); } }, 60000);
  refresh();
})();
