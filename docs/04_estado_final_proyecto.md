# Estado final del proyecto pulido

Fecha: 2026-07-06

## Resultado

El proyecto quedo organizado de forma conservadora:

- archivos activos fuera de `archive/`: 1207;
- archivos archivados: 386;
- temporales eliminados: 12;
- temporales activos detectados (`.pyc`, `__pycache__`, `.ipynb_checkpoints`, `.bak`): 0.

## Raiz limpia

La raiz mantiene un solo lanzador `.bat` de uso directo:

- `README.md`
- `requirements.txt`
- `129_monitor_fondo3_ACTUALIZA_Y_ABRE.py`
- `ACTUALIZAR_Y_ABRIR_MONITOR_FONDO3.bat`

## Material didactico agregado

Notebook nuevo:

```text
notebooks/02_desarrollo_modelo_fondo3_paso_a_paso.ipynb
```

Contenido:

- objetivo del proyecto;
- archivos clave;
- lectura de metricas;
- modelos probados;
- ranking de validacion;
- ganadores por AFP;
- hiperparametros;
- importancia de variables;
- simulacion historica real vs estimado;
- modelo congelado;
- pronostico congelado;
- entrenamiento pedagogico con `Pipeline` y varios estimadores;
- comparacion de metricas MAE, RMSE, R2 y MAPE.

## Documentacion activa

- `docs/01_auditoria_archivos.md`
- `docs/02_mapa_funcional_proyecto.md`
- `docs/03_limpieza_proyecto.md`
- `docs/04_estado_final_proyecto.md`

## Archivo interno

Los archivos retirados del flujo activo estan en:

```text
archive/20260706_limpieza_proyecto/
```

Manifiesto:

```text
archive/20260706_limpieza_proyecto/manifest_limpieza.csv
```
