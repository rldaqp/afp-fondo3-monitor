# Limpieza del proyecto - 2026-07-06

## Resumen

Se aplico una limpieza conservadora del proyecto AFP Fondo 3.

Acciones realizadas:

- Se movieron archivos historicos y generados a `archive/20260706_limpieza_proyecto/`.
- Se eliminaron temporales tecnicos regenerables.
- No se tocaron datos raw, historicos, bases canonicas, manifiestos operativos ni modelos entrenados.
- Se regenero un manifiesto de archivo en `archive/20260706_limpieza_proyecto/manifest_limpieza.csv`.

## Que se archivo

Se archivaron principalmente:

- scripts numerados antiguos que estaban en la raiz;
- lanzadores `.bat` versionados antiguos;
- scripts `BACKUP`, `RESPALDO` y copias `(1)` en `src/`;
- scripts de instalacion/correccion puntual ya aplicados;
- graficos generados por modelos anteriores;
- logs y respaldos de scripts.

## Que se elimino

Se eliminaron solo temporales claros:

- archivos `.pyc`;
- carpetas `__pycache__`;
- checkpoints automaticos de notebooks;
- archivos `.bak`.

## Que se mantuvo en la raiz

La raiz queda orientada a uso humano y con un solo lanzador principal:

- `README.md`
- `requirements.txt`
- `129_monitor_fondo3_ACTUALIZA_Y_ABRE.py`
- `ACTUALIZAR_Y_ABRIR_MONITOR_FONDO3.bat`
- carpetas principales: `src/`, `data/`, `automatizacion/`, `notebooks/`, `docs/`, `archive/`

## Recuperacion

Si algun archivo archivado vuelve a ser necesario, restaurarlo desde:

```text
archive/20260706_limpieza_proyecto/
```

El archivo mantiene la estructura relativa original, por lo que se puede copiar de vuelta al mismo lugar dentro del proyecto.

## Nota de seguridad

Esta limpieza priorizo no romper el flujo operativo. Por eso se archivo mas de lo que se elimino.
