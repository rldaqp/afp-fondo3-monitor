# Migracion a GitHub Actions y GitHub Pages

## Archivos indispensables

- `129_monitor_fondo3_ACTUALIZA_Y_ABRE.py`: orquesta la actualizacion y genera el HTML principal.
- `requirements.txt`: dependencias de Python para GitHub Actions.
- `src/80_monitor_sbs_y_validar_pronosticos.py`: consulta SBS y actualiza el pronostico.
- `src/79_congelar_modelo_y_estimar_prospectivamente.py`: genera estimaciones vigentes.
- `src/79C_exportar_ecuaciones_exactas_y_contribuciones.py`: genera contribuciones por indices.
- `src/99_cuota_sintetica_intradia.py`: guarda el historial intradia del valor cuota estimado.
- `data/processed/*.csv`: bases historicas, canastas, metricas y salidas que el monitor necesita para reconstruirse.
- `public/index.html`: salida que se publica en GitHub Pages.

## Rutas corregidas

El flujo de GitHub no usa `C:\Users`, `J:\`, Google Drive local, `.bat` ni `.vbs`.
Los scripts trabajan desde la raiz del repositorio usando `Path(__file__).resolve()`.

## Datos sensibles

No se detectaron claves privadas escritas en el codigo. Hay soporte opcional para `OPENFIGI_API_KEY`
en scripts exploratorios; si se usa, debe configurarse como secret de GitHub, no en archivos del repo.

## GitHub Actions o servidor externo

GitHub Actions + GitHub Pages es suficiente para actualizar cada hora y publicar un HTML estatico para celular.
Un servidor externo solo seria recomendable si se necesita ejecucion permanente, datos en tiempo real por minuto,
autenticacion privada o una API dinamica.

## Publicacion

El workflow `.github/workflows/update-monitor.yml`:

1. instala Python 3.11;
2. instala `requirements.txt`;
3. ejecuta `python scripts/build_pages.py`;
4. guarda cambios en `data/` y `public/`;
5. publica `public/` con GitHub Pages.

La ejecucion es manual (`workflow_dispatch`) y automatica cada hora en dias habiles de Lima.
