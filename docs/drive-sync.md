# Sincronizacion de operaciones con Google Drive

La bitacora de operaciones del monitor se guarda primero en el navegador. Para que tambien quede en Google Drive, la pagina llama a una Web app de Google Apps Script mediante JSONP.

Si Habitat no guarda en Drive y la pagina muestra timeout o que el puente no esta actualizado, el problema esta en el despliegue de Apps Script, no en el calculo del VC.

## Archivo listo para pegar

Usa este codigo:

```text
apps-script/fondo3-drive-sync.gs
```

Ese puente soporta las dos hojas:

- `Profuturo`
- `Habitat`

Y responde a estas acciones:

- `ping`
- `list`
- `upsert`
- `delete`

## Pasos en Google

1. Abre la hoja de Google Sheets donde guardas las operaciones.
2. Ve a `Extensiones > Apps Script`.
3. Pega el contenido de `apps-script/fondo3-drive-sync.gs`.
4. En `Configuracion del proyecto > Propiedades de secuencia de comandos`, crea `SYNC_KEY`.
5. Usa la misma clave `SYNC_KEY` en el campo de clave de la pagina del monitor.
6. Ve a `Implementar > Nueva implementacion > Aplicacion web`.
7. Configura:
   - Ejecutar como: tu usuario.
   - Quien tiene acceso: cualquier usuario.
8. Copia la URL que termina en `/exec` y pegala en el monitor.

## Verificacion rapida

La URL debe responder algo parecido a esto cuando se llama con `action=ping`, `fund=HABITAT`, `key=TU_CLAVE` y `callback=cb`:

```js
cb({"ok":true,"routing":true,"fund":"HABITAT","sheet":"Habitat"});
```

Si devuelve una pantalla de inicio de sesion de Google, el despliegue no esta publico para la pagina de GitHub Pages. En ese caso hay que volver a desplegar la Web app con acceso para cualquier usuario.
