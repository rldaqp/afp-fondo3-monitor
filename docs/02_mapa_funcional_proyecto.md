# Mapa funcional del proyecto AFP Fondo 3

## Objetivo

El proyecto construye un flujo operativo para monitorear y estimar el valor cuota del AFP Fondo 3 antes o alrededor de la publicacion oficial de la SBS.

La idea central es:

1. Capturar datos oficiales SBS y factores de mercado.
2. Construir bases historicas auditables.
3. Probar modelos de nowcasting y estimacion prospectiva.
4. Escoger una configuracion con metricas fuera de muestra.
5. Congelar un modelo operativo.
6. Generar monitores y tableros para seguimiento diario.

## Estructura actual

| Carpeta | Uso |
|---|---|
| `src/` | Scripts principales del pipeline, entrenamiento, validacion, congelamiento y monitores. |
| `data/raw/` | Datos fuente descargados desde SBS y mercados. No tocar sin respaldo. |
| `data/processed/` | Bases limpias, metricas, predicciones, manifiestos, dashboards y salidas operativas. |
| `data/processed/modelos_modelo64/` y `data/processed/modelos_modelo66/` | Artefactos `.joblib` de modelos entrenados. |
| `automatizacion/` | Tareas Windows para actualizacion y monitoreo. |
| `notebooks/` | Material didactico y exploratorio. |
| `docs/` | Auditoria, mapa funcional y registro de limpieza. |
| `archive/20260706_limpieza_proyecto/` | Versiones antiguas, backups, scripts de instalacion ya aplicados, graficos y logs archivados. |

## Flujo recomendado

```text
data/raw
  -> src/02..08 inspeccion, historicos y factores
  -> src/09..22 modelos base y pesos reales
  -> src/23..40 composicion CA0001, cartera y taxonomia
  -> src/41..68 validacion, comparacion de modelos y metricas
  -> src/69..78 seleccion y poda de canasta final
  -> src/79 congelamiento prospectivo
  -> src/79C explicacion/contribuciones
  -> src/80 y monitores posteriores
```

## Modelo operativo observado

El modelo vigente parece estar alrededor de:

- `src/79_congelar_modelo_y_estimar_prospectivamente.py`
- `data/processed/ca0001_modelo79_manifiesto_modelo_congelado.json`
- `data/processed/ca0001_modelo79_canasta_congelada.csv`
- `data/processed/ca0001_modelo79_primer_pronostico_congelado.csv`
- `data/processed/ca0001_monitor_fondo3_actualizado.html`

La seleccion previa de modelos esta sustentada principalmente por salidas de `modelo64`, `modelo65`, `modelo66`, `modelo67` y `modelo68`, con metricas comparables por AFP.

## Reglas de proteccion

No tocar sin respaldo:

- `data/raw/**`
- bases historicas y canonicas en `data/processed/`
- `sbs_fondo3_vintages.csv`
- `ca0001_modelo79_*`
- modelos `.joblib`
- manifiestos JSON de modelos congelados

## Reglas para seguir mejorando

- Mantener la raiz con pocos lanzadores humanos.
- Mantener scripts activos en `src/`.
- No volver a crear backups sueltos en `src/`; usar `archive/`.
- Agregar cada cambio relevante a `docs/`.
- Antes de borrar datos, moverlos primero a `archive/` y dejar manifiesto.
