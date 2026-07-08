# AFP Fondo 3 - Monitor en GitHub Pages

Proyecto para capturar datos SBS, actualizar estimaciones del Fondo 3 y publicar un monitor HTML estatico mediante GitHub Actions + GitHub Pages.

## Uso en GitHub

El flujo principal esta en:

```text
.github/workflows/update-monitor.yml
```

Ese workflow:

- se ejecuta manualmente desde la pestana **Actions**;
- se ejecuta automaticamente cada hora en dias habiles de America/Lima;
- instala las dependencias de `requirements.txt`;
- ejecuta `python scripts/build_pages.py`;
- actualiza las bases necesarias en `data/`;
- publica `public/index.html` en GitHub Pages.

## Uso local sin .bat

```powershell
python -m pip install -r requirements.txt
python scripts/build_pages.py
```

La pagina principal queda en:

```text
public/index.html
```

## Estructura

| Ruta | Uso |
|---|---|
| `129_monitor_fondo3_ACTUALIZA_Y_ABRE.py` | Script principal que actualiza y genera el monitor. |
| `scripts/build_pages.py` | Adaptador para GitHub Pages: ejecuta el monitor y copia HTML a `public/`. |
| `.github/workflows/update-monitor.yml` | Automatizacion en GitHub Actions. |
| `src/` | Scripts del pipeline, SBS, pronosticos, contribuciones e intradia. |
| `data/raw/` | Datos fuente conservados para reproducibilidad. |
| `data/processed/` | Bases procesadas y HTML generado. |
| `public/` | Carpeta publicada por GitHub Pages. |
| `docs/` | Auditorias y documentacion tecnica. |

## Archivos operativos importantes

- `src/80_monitor_sbs_y_validar_pronosticos.py`
- `src/79_congelar_modelo_y_estimar_prospectivamente.py`
- `src/79C_exportar_ecuaciones_exactas_y_contribuciones.py`
- `src/99_cuota_sintetica_intradia.py`
- `data/processed/ca0001_modelo79_manifiesto_modelo_congelado.json`
- `data/processed/ca0001_modelo79_canasta_congelada.csv`
- `data/processed/ca0001_modelo79_primer_pronostico_congelado.csv`
- `data/processed/ca0001_monitor_fondo3_actualizado.html`

## Datos sensibles

No se deben subir claves en archivos. Si algun script requiere `OPENFIGI_API_KEY`, configuralo como secret del repositorio en GitHub.

## Nota

Esta copia reemplaza los lanzadores Windows `.bat/.vbs` por GitHub Actions. La carpeta original en Google Drive no se elimina ni se modifica por esta migracion.
