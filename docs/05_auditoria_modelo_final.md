# Auditoria del modelo final AFP Fondo 3

Fecha: 2026-07-07

## Respuesta corta

Si: el proyecto uso una division temporal cercana a 60% / 20% / 20%.

La evidencia esta en `data/processed/ca0001_modelo50_division_temporal.csv`:

| Segmento | Fechas | Observaciones | Uso |
|---|---|---:|---|
| entrenamiento_descubrimiento | 2015-01-05 a 2021-11-12 | 1779 | seleccionar rezagos, variables y correlaciones iniciales |
| validacion | 2021-11-15 a 2024-02-23 | 593 | elegir configuraciones/modelos |
| prueba_intocable | 2024-02-26 a 2026-06-30 | 593 | auditar desempeno final |

La proporcion aproximada es 60% / 20% / 20%.

## Por que el notebook se veia diferente al monitor

El grafico del notebook usaba `data/processed/ca0001_modelo66_simulaciones_cuota.csv`.

Ese archivo pertenece a una etapa anterior de competencia de modelos. Ademas contiene muchas combinaciones de:

- AFP;
- modelo;
- tarea;
- segmento;
- fechas repetidas.

Si se grafica sin filtrar una sola configuracion final, aparecen saltos verticales y lineas raras. Ese grafico no debe interpretarse como la linea historica final del monitor.

El monitor, en cambio, prioriza `data/processed/ca0001_modelo78_simulacion_publicacion_5d.csv`, que corresponde a la canasta final evaluada como simulacion de publicacion con retraso. Por eso en el monitor las lineas real y estimada se ven mas estables y comparables.

## Ruta real hacia el modelo final

El camino observado es:

1. `modelo50`: define la division temporal 60/20/20.
2. `modelo64`: compara modelos lineales/robustos/ARDL.
3. `modelo65`: compara ARIMAX, rolling ridge y EW-Ridge.
4. `modelo66`: agrega no lineales y objetivo directo; elige por validacion.
5. `modelo68`: calibra amplitud y regimen usando validacion.
6. `modelo78`: consolida la canasta final y la poda usando validacion; prueba queda como auditoria.
7. `modelo79`: congela el modelo prospectivo para operacion diaria.
8. `129_monitor_fondo3_ACTUALIZA_Y_ABRE.py`: genera el monitor HTML operativo.

## Evidencia de seleccion

`ca0001_modelo66_resumen.json` dice:

- fin de entrenamiento: 2021-11-12;
- fin de validacion: 2024-02-23;
- criterio: menor MAPE de cuota en validacion, desempate por MAE de retorno acumulado y P90.

Ganadores en `modelo66`:

| AFP | Modelo elegido en validacion | MAPE validacion |
|---|---|---:|
| Habitat | EW_RIDGE_HL60_A0.001 | 0.7411 |
| Integra | DIARIO_RIDGE | 0.6502 |
| Prima | DIARIO_RIDGE | 0.6111 |
| Profuturo | DIARIO_RIDGE | 0.6223 |

Luego `modelo68` recalibra y mejora la etapa:

| AFP | Calibracion seleccionada | MAPE validacion |
|---|---|---:|
| Habitat | AFIN_W250 | 0.5449 |
| Integra | IDENTIDAD_EW | 0.4659 |
| Prima | IDENTIDAD_EW | 0.4466 |
| Profuturo | HUBER_W120 | 0.4857 |

Finalmente `modelo78` define la canasta final/podada y audita en prueba:

| AFP | Modelo final | Factores | MAPE prueba | Direccion acumulada prueba |
|---|---|---:|---:|---:|
| Habitat | CANASTA_PODADA / EW_RIDGE | 9 | 0.6381 | 83.64% |
| Integra | CANASTA_PODADA / EW_RIDGE | 4 | 0.7188 | 79.76% |
| Prima | CANASTA_PODADA / EW_RIDGE | 3 | 0.7831 | 81.28% |
| Profuturo | CANASTA_PODADA / EW_RIDGE | 5 | 0.7513 | 82.80% |

## Modelo operativo actual

El modelo operativo congelado esta en:

- `data/processed/ca0001_modelo79_manifiesto_modelo_congelado.json`
- `data/processed/ca0001_modelo79_canasta_congelada.csv`
- `data/processed/ca0001_modelo79_primer_pronostico_congelado.csv`

El manifiesto indica que usa la canasta final podada del modulo 78 y que no vuelve a seleccionar variables cada dia. Eso es correcto para produccion porque evita recalibrar el modelo mirando resultados nuevos.

## Conclusion

La idea general del usuario es correcta: se partio de un esquema temporal 60/20/20 y la seleccion se hizo con validacion.

La precision importante es esta:

- entrenamiento/descubrimiento sirve para construir candidatos;
- validacion sirve para elegir modelos, regularizacion, calibracion y poda;
- prueba sirve para auditar;
- el modelo final operativo no es el primer ganador de `modelo66`, sino la canasta final podada/congelada que queda luego de `modelo78` y `modelo79`.

El notebook anterior mezclaba una etapa intermedia con la vista operativa final. Debe usar `modelo78` para explicar el monitor y `modelo66` solo para explicar la competencia de modelos.
