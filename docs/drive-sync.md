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
4. No crees propiedades de script: la clave ya se lee desde la pestana `Config`, celda `B4`.
5. Ve a `Implementar > Administrar implementaciones`.
6. Edita la aplicacion web existente, selecciona `Nueva version` y pulsa `Implementar`.
7. Configura:
   - Ejecutar como: tu usuario.
   - Quien tiene acceso: cualquier usuario.
8. Puedes mantener la URL `/exec` existente que esta en `Config!B5`.

## Verificacion rapida

La URL debe responder algo parecido a esto cuando se llama con `action=ping`, `fund=HABITAT`, `key=TU_CLAVE` y `callback=cb`:

```js
cb({"ok":true,"routing":true,"fund":"HABITAT","sheet":"Habitat"});
```

Si devuelve una pantalla de inicio de sesion de Google, el despliegue no esta publico para la pagina de GitHub Pages. En ese caso hay que volver a desplegar la Web app con acceso para cualquier usuario.
