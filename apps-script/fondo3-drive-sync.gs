// AFP Fondo 3 - puente JSONP para guardar operaciones en Google Sheets.
//
// Este es el puente compatible con la hoja existente "Operaciones Fondo 3".
// La clave se lee desde la pestana Config, celda B4. No hace falta crear
// propiedades de secuencia de comandos en Apps Script.

const SPREADSHEET_ID = '1Bktbl-tRBIJnBsZzgXUNajj2_I9l6Slpsseno7zcRe8';
const DATA_SHEETS = { PROFUTURO: 'Profuturo', HABITAT: 'Habitat' };
const CONFIG_SHEET = 'Config';

function doGet(e) {
  const p = (e && e.parameter) || {};
  const callback = sanitizeCallback_(p.callback || '');
  try {
    validateKey_(p.key || '');
    const action = String(p.action || 'list').toLowerCase();
    const fund = resolveFund_(p.fund);
    let data;

    if (action === 'ping') {
      data = {
        ok: true,
        service: 'Fondo3 Drive Sync v2',
        routing: true,
        fund: fund,
        sheet: DATA_SHEETS[fund],
        now: new Date().toISOString()
      };
    } else if (action === 'list') {
      data = { ok: true, routing: true, fund: fund, rows: listRows_(fund) };
    } else if (action === 'upsert') {
      if (!p.payload) throw new Error('Falta payload');
      const row = JSON.parse(p.payload);
      data = { ok: true, routing: true, fund: fund, row: upsertRow_(row, fund) };
    } else if (action === 'delete') {
      if (!p.id) throw new Error('Falta id');
      deleteRow_(p.id, fund);
      data = { ok: true, routing: true, fund: fund, id: p.id };
    } else {
      throw new Error('Accion no soportada: ' + action);
    }

    return respond_(data, callback);
  } catch (err) {
    return respond_({ ok: false, error: String(err && err.message ? err.message : err) }, callback);
  }
}

function spreadsheet_() {
  return SpreadsheetApp.openById(SPREADSHEET_ID);
}

function validateKey_(provided) {
  const sh = spreadsheet_().getSheetByName(CONFIG_SHEET);
  if (!sh) throw new Error('No existe la pestana Config');
  const expected = String(sh.getRange('B4').getDisplayValue() || '').trim();
  if (!expected || expected === 'PENDIENTE') throw new Error('SYNC_KEY no configurada');
  if (String(provided || '') !== expected) throw new Error('Clave de sincronizacion incorrecta');
}

function resolveFund_(value) {
  const fund = String(value || '').trim().toUpperCase();
  if (!Object.prototype.hasOwnProperty.call(DATA_SHEETS, fund)) {
    throw new Error('Fondo invalido o ausente. Use PROFUTURO o HABITAT.');
  }
  return fund;
}

function dataSheet_(fund) {
  const name = DATA_SHEETS[fund];
  const sh = spreadsheet_().getSheetByName(name);
  if (!sh) throw new Error('No existe la pestana ' + name);
  return sh;
}

function listRows_(fund) {
  const sh = dataSheet_(fund);
  const last = sh.getLastRow();
  if (last < 2) return [];
  const values = sh.getRange(2, 1, last - 1, 20).getValues();
  return values.map(function(r) {
    const raw = r[19];
    let row = null;
    if (raw) {
      try { row = JSON.parse(String(raw)); } catch (e) {}
    }
    if (!row) row = rowFromColumns_(r);
    if (row && row.id) row.fund = fund;
    return row;
  }).filter(function(r) { return r && r.id; });
}

function rowFromColumns_(r) {
  return {
    id: r[0] || '',
    confirmed: String(r[14]).toUpperCase() === 'SI',
    capital: numberOrNull_(r[4]),
    entry_requested: textOrNull_(r[2]),
    entry_date: textOrNull_(r[3]),
    entry_est_vc: numberOrNull_(r[5]),
    entry_sbs_vc: numberOrNull_(r[6]),
    exit_requested: textOrNull_(r[7]),
    exit_date: textOrNull_(r[8]),
    exit_est_vc: numberOrNull_(r[9]),
    exit_sbs_vc: numberOrNull_(r[10]),
    created_at: textOrNull_(r[15]),
    confirmed_at: textOrNull_(r[16]),
    closed_at: textOrNull_(r[17]),
    origin: textOrNull_(r[18]) || 'DRIVE'
  };
}

function upsertRow_(obj, fund) {
  if (!obj || !obj.id) throw new Error('La operacion no tiene ID');
  const sh = dataSheet_(fund);
  const last = sh.getLastRow();
  let target = last + 1;
  if (last >= 2) {
    const ids = sh.getRange(2, 1, last - 1, 1).getDisplayValues().flat();
    const idx = ids.findIndex(function(x) { return String(x) === String(obj.id); });
    if (idx >= 0) target = idx + 2;
  }
  obj.fund = fund;
  obj.origin = obj.origin || ('VISOR GITHUB - ' + fund);
  const row = columnsFromObject_(obj);
  sh.getRange(target, 1, 1, 20).setValues([row]);
  SpreadsheetApp.flush();
  return obj;
}

function deleteRow_(id, fund) {
  const sh = dataSheet_(fund);
  const last = sh.getLastRow();
  if (last < 2) return;
  const ids = sh.getRange(2, 1, last - 1, 1).getDisplayValues().flat();
  const idx = ids.findIndex(function(x) { return String(x) === String(id); });
  if (idx >= 0) sh.deleteRow(idx + 2);
}

function columnsFromObject_(o) {
  const estRet = ratio_(o.entry_est_vc, o.exit_est_vc);
  const realRet = ratio_(o.entry_sbs_vc, o.exit_sbs_vc);
  const diff = estRet !== null && realRet !== null ? realRet - estRet : null;
  return [
    o.id || '',
    o.exit_date ? 'CERRADA' : 'ABIERTA',
    o.entry_requested || '',
    o.entry_date || '',
    numberOrBlank_(o.capital),
    numberOrBlank_(o.entry_est_vc),
    numberOrBlank_(o.entry_sbs_vc),
    o.exit_requested || '',
    o.exit_date || '',
    numberOrBlank_(o.exit_est_vc),
    numberOrBlank_(o.exit_sbs_vc),
    numberOrBlank_(estRet),
    numberOrBlank_(realRet),
    numberOrBlank_(diff),
    o.confirmed ? 'SI' : 'NO',
    o.created_at || '',
    o.confirmed_at || '',
    o.closed_at || '',
    o.origin || ('VISOR GITHUB - ' + (o.fund || '')),
    JSON.stringify(o)
  ];
}

function ratio_(a, b) {
  const x = Number(a), y = Number(b);
  if (!isFinite(x) || !isFinite(y) || x === 0) return null;
  return y / x - 1;
}

function numberOrBlank_(v) {
  if (v === null || v === undefined || v === '') return '';
  const n = Number(v);
  return isFinite(n) ? n : '';
}

function numberOrNull_(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

function textOrNull_(v) {
  if (v === null || v === undefined || v === '') return null;
  if (Object.prototype.toString.call(v) === '[object Date]') {
    return Utilities.formatDate(v, 'America/Lima', "yyyy-MM-dd'T'HH:mm:ssXXX");
  }
  return String(v);
}

function sanitizeCallback_(name) {
  const s = String(name || '');
  return /^[A-Za-z_$][0-9A-Za-z_$.]*$/.test(s) ? s : '';
}

function respond_(obj, callback) {
  const json = JSON.stringify(obj);
  if (callback) {
    return ContentService.createTextOutput(callback + '(' + json + ');')
      .setMimeType(ContentService.MimeType.JAVASCRIPT);
  }
  return ContentService.createTextOutput(json)
    .setMimeType(ContentService.MimeType.JSON);
}
