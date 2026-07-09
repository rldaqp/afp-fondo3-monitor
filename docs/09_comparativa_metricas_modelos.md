# Comparativa de metricas de modelos Fondo 3

## Como leer las metricas

- **MAE retorno**: error promedio. Menor es mejor.
- **RMSE retorno**: error castigando mas los errores grandes. Menor es mejor.
- **R2**: cuanto explica el modelo. Mayor es mejor.
- **Correlacion**: si el retorno estimado se mueve parecido al real. Mayor es mejor.
- **MAPE cuota**: error porcentual sobre valor cuota. Menor es mejor.
- **Direccion**: porcentaje de veces que acierta sube/baja. Mayor es mejor.
- **P90 error**: en 90% de los casos el error queda por debajo de ese valor. Menor es mejor.

## Modelo actual del monitor

Este es el modelo que hoy alimenta el monitor: **EW-Ridge con canasta podada**.

| afp | modelo | observaciones | n_factores | mae_retorno | rmse_retorno | r2 | mape_cuota_pct | direccion_pct | p90_error_abs_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Habitat | Actual monitor: EW-Ridge canasta podada | 593 | 9 | 0.0034 | 0.0050 | 0.5457 | 0.64% | 83.64% | 1.47% |
| Integra | Actual monitor: EW-Ridge canasta podada | 593 | 4 | 0.0038 | 0.0056 | 0.4982 | 0.72% | 79.76% | 1.73% |
| Prima | Actual monitor: EW-Ridge canasta podada | 593 | 3 | 0.0040 | 0.0061 | 0.4660 | 0.78% | 81.28% | 1.92% |
| Profuturo | Actual monitor: EW-Ridge canasta podada | 593 | 5 | 0.0040 | 0.0060 | 0.4638 | 0.75% | 82.80% | 1.82% |

## Mejores modelos con pesos reales

Estos modelos prueban si usar pesos reales de cartera mejora frente a modelos sin pesos. Se elige el mejor por menor RMSE dentro de cada AFP.

| afp | modelo | observaciones | n_factores | mae_retorno | rmse_retorno | r2 | correlacion | direccion_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Habitat | M2_hibrido / lag0_1_2 | 372 | 60 | 0.0043 | 0.0064 | 0.4321 | 0.7311 | 75.27% |
| Integra | M1_pesos_reales / lag0 | 372 | 10 | 0.0046 | 0.0067 | 0.4525 | 0.7859 | 75.27% |
| Prima | M1_pesos_reales / lag0 | 372 | 10 | 0.0049 | 0.0072 | 0.4208 | 0.7683 | 76.61% |
| Profuturo | M2_hibrido / lag0_1 | 372 | 40 | 0.0049 | 0.0073 | 0.4133 | 0.7417 | 75.81% |

## Detalle de modelos con pesos reales

- **M0_sin_pesos**: usa factores de mercado sin pesos de cartera.
- **M1_pesos_reales**: usa factores modulados por pesos reales de cartera.
- **M2_hibrido**: combina factores sin pesos y factores con pesos reales.

| afp | modelo | observaciones | n_factores | mae_retorno | rmse_retorno | r2 | correlacion | direccion_pct | ranking_rmse |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Habitat | M0_sin_pesos / lag0_1_2 | 372 | 30 | 0.0044 | 0.0066 | 0.4075 | 0.7226 | 74.46% | 3 |
| Habitat | M1_pesos_reales / lag0_1_2 | 372 | 30 | 0.0043 | 0.0065 | 0.4198 | 0.7347 | 75.27% | 2 |
| Habitat | M2_hibrido / lag0_1_2 | 372 | 60 | 0.0043 | 0.0064 | 0.4321 | 0.7311 | 75.27% | 1 |
| Integra | M0_sin_pesos / lag0 | 372 | 10 | 0.0048 | 0.0070 | 0.3996 | 0.7756 | 75.27% | 3 |
| Integra | M1_pesos_reales / lag0 | 372 | 10 | 0.0046 | 0.0067 | 0.4525 | 0.7859 | 75.27% | 1 |
| Integra | M2_hibrido / lag0 | 372 | 20 | 0.0047 | 0.0068 | 0.4350 | 0.7860 | 76.08% | 2 |
| Prima | M0_sin_pesos / lag0 | 372 | 10 | 0.0051 | 0.0074 | 0.3840 | 0.7816 | 76.08% | 3 |
| Prima | M1_pesos_reales / lag0 | 372 | 10 | 0.0049 | 0.0072 | 0.4208 | 0.7683 | 76.61% | 1 |
| Prima | M2_hibrido / lag0 | 372 | 20 | 0.0049 | 0.0072 | 0.4151 | 0.7872 | 76.34% | 2 |
| Profuturo | M0_sin_pesos / lag0_1 | 372 | 20 | 0.0050 | 0.0074 | 0.3907 | 0.7430 | 75.27% | 3 |
| Profuturo | M1_pesos_reales / lag0_1 | 372 | 20 | 0.0050 | 0.0074 | 0.4010 | 0.7374 | 74.73% | 2 |
| Profuturo | M2_hibrido / lag0_1 | 372 | 40 | 0.0049 | 0.0073 | 0.4133 | 0.7417 | 75.81% | 1 |

## Criterio de eleccion propuesto

Para elegir modelo no basta una sola metrica. Propongo este orden:

1. Que tenga menor **RMSE** y **MAE**.
2. Que mantenga buena **direccion**.
3. Que tenga buena **correlacion**.
4. Que supere al modelo simple de ultima cuota SBS.
5. Que sea explicable: si dos modelos empatan, preferir el mas simple.

## Lectura actual

El modelo actual del monitor tiene una direccion alta, cerca de 80% a 84%, y MAPE de cuota alrededor de 0.64% a 0.78%.

Los modelos con pesos reales muestran que incorporar cartera ayuda en varias AFP:

- Habitat: gana el hibrido M2.
- Integra: gana M1 con pesos reales.
- Prima: gana M1 con pesos reales por RMSE, aunque M2 tiene mayor correlacion.
- Profuturo: gana el hibrido M2.

Importante: estas tablas no son todavia una competencia perfecta entre el monitor actual y la futura cartera replicante intradia, porque vienen de pruebas historicas distintas. La siguiente fase debe poner todos los modelos en el mismo periodo y con la misma regla de evaluacion.
