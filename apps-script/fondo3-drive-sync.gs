// AFP Fondo 3 - puente JSONP para guardar operaciones en Google Sheets.
//
// Uso:
// 1. Abre la hoja de Google Sheets que usas como respaldo.
// 2. Extensiones > Apps Script.
// 3. Pega este archivo completo.
// 4. En Configuracion del proyecto > Propiedades de secuencia de comandos,
//    crea SYNC_KEY con la misma clave que escribes en la pagina web.
// 5. Implementar > Nueva implementacion > Aplicacion web.
//    Ejecutar como: tu usuario.
//    Quien tiene acceso: Cualquier usuario.
// 6. Copia la URL que termina en /exec en la pagina del monitor.

const F3_HEADERS = [
  'id',
  'fund',
  'created_at',
  'confirmed',
  'confirmed_at',
  'capital',
  'entry_requested',
  'entry_date',
  'entry_est_vc',
  'entry_sbs_vc',
  'exit_requested',
  'exit_date',
  'exit_est_vc',
  'exit_sbs_vc',
  'closed_at'
];

const F3_SHEETS = {
  PROFUTURO: 'Profuturo',
  HABITAT: 'Habitat'
};

function doGet(e) {
  const params = (e && e.parameter) || {};
  const callback = params.callback || 'callback';

  try {
    const action = String(params.action || 'ping').toLowerCase();
    const fund = normalizeFund_(params.fund);

    if (action === 'ping') {
      requireKey_(params.key);
      return jsonp_(callback, {
        ok: true,
        routing: true,
        fund: fund,
        sheet: F3_SHEETS[fund]
      });
    }

    requireKey_(params.key);

    if (action === 'list') {
      return jsonp_(callback, {
        ok: true,
        routing: true,
        fund: fund,
        rows: listRows_(fund)
      });
    }

    if (action === 'upsert') {
      const row = parsePayload_(params.payload);
      row.fund = fund;
      upsertRow_(fund, row);
      return jsonp_(callback, {
        ok: true,
        routing: true,
        fund: fund
      });
    }

    if (action === 'delete') {
      deleteRow_(fund, params.id);
      return jsonp_(callback, {
        ok: true,
        routing: true,
        fund: fund
      });
    }

    throw new Error('Accion no soportada: ' + action);
  } catch (err) {
    return jsonp_(callback, {
      ok: false,
      error: err && err.message ? err.message : String(err)
    });
  }
}

function normalizeFund_(fund) {
  const value = String(fund || 'PROFUTURO').trim().toUpperCase();
  if (!F3_SHEETS[value]) {
    throw new Error('Fondo no soportado: ' + value);
  }
  return value;
}

function requireKey_(key) {
  const expected = PropertiesService.getScriptProperties().getProperty('SYNC_KEY');
  if (!expected) {
    throw new Error('Falta configurar SYNC_KEY en Apps Script.');
  }
  if (String(key || '') !== String(expected)) {
    throw new Error('La clave de sincronizacion no es valida.');
  }
}

function parsePayload_(payload) {
  if (!payload) {
    throw new Error('Falta payload.');
  }
  const row = JSON.parse(payload);
  if (!row || !row.id) {
    throw new Error('La operacion no tiene id.');
  }
  return row;
}

function getSheet_(fund) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const name = F3_SHEETS[fund];
  let sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
  }
  ensureHeaders_(sheet);
  return sheet;
}

function ensureHeaders_(sheet) {
  const lastCol = Math.max(sheet.getLastColumn(), F3_HEADERS.length);
  const current = sheet.getRange(1, 1, 1, lastCol).getValues()[0].map(String);
  const present = new Set(current.filter(Boolean));
  const merged = current.filter(Boolean);

  F3_HEADERS.forEach(header => {
    if (!present.has(header)) {
      merged.push(header);
    }
  });

  if (merged.length === 0) {
    sheet.getRange(1, 1, 1, F3_HEADERS.length).setValues([F3_HEADERS]);
    return;
  }

  sheet.getRange(1, 1, 1, merged.length).setValues([merged]);
}

function headers_(sheet) {
  return sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].map(String);
}

function listRows_(fund) {
  const sheet = getSheet_(fund);
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    return [];
  }

  const headers = headers_(sheet);
  return sheet.getRange(2, 1, lastRow - 1, headers.length).getValues()
    .map(values => objectFromRow_(headers, values))
    .filter(row => row.id);
}

function upsertRow_(fund, row) {
  const sheet = getSheet_(fund);
  const headers = headers_(sheet);
  const idCol = headers.indexOf('id') + 1;
  const values = rowFromObject_(headers, row);
  const found = findRowById_(sheet, idCol, row.id);

  if (found) {
    sheet.getRange(found, 1, 1, headers.length).setValues([values]);
  } else {
    sheet.appendRow(values);
  }
}

function deleteRow_(fund, id) {
  if (!id) {
    throw new Error('Falta id para eliminar.');
  }

  const sheet = getSheet_(fund);
  const headers = headers_(sheet);
  const idCol = headers.indexOf('id') + 1;
  const found = findRowById_(sheet, idCol, id);
  if (found) {
    sheet.deleteRow(found);
  }
}

function findRowById_(sheet, idCol, id) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    return 0;
  }

  const ids = sheet.getRange(2, idCol, lastRow - 1, 1).getValues();
  for (let i = 0; i < ids.length; i += 1) {
    if (String(ids[i][0]) === String(id)) {
      return i + 2;
    }
  }
  return 0;
}

function objectFromRow_(headers, values) {
  const row = {};
  headers.forEach((header, index) => {
    if (!header) {
      return;
    }
    row[header] = normalizeCell_(values[index]);
  });
  return row;
}

function rowFromObject_(headers, row) {
  return headers.map(header => {
    if (!header) {
      return '';
    }
    const value = row[header];
    if (value === undefined || value === null) {
      return '';
    }
    return value;
  });
}

function normalizeCell_(value) {
  if (value === '') {
    return null;
  }
  if (value instanceof Date) {
    return value.toISOString();
  }
  return value;
}

function jsonp_(callback, payload) {
  const safe = String(callback || 'callback').match(/^[A-Za-z_$][0-9A-Za-z_$]*(?:\.[A-Za-z_$][0-9A-Za-z_$]*)*$/)
    ? callback
    : 'callback';
  return ContentService
    .createTextOutput(safe + '(' + JSON.stringify(payload) + ');')
    .setMimeType(ContentService.MimeType.JAVASCRIPT);
}
