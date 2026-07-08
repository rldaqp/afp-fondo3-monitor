# Auditoria tecnica profesional - AFP Fondo 3

Fecha de auditoria: 2026-07-07

Proyecto auditado:

```text
E:\Mi unidad (rldaqp@gmail.com)\01. DSIS OEFA\afp_fondo3_inicio\afp_fondo3_inicio
```

## 1. Alcance de esta auditoria

Esta auditoria revisa:

- objetivo del proyecto;
- fuentes de datos y paginas/APIs usadas;
- estructura del pipeline;
- metodo matematico de correlaciones;
- modelos evaluados;
- particion entrenamiento/validacion/prueba;
- metodologia de seleccion;
- modelo final congelado;
- resultados principales;
- limitaciones y puntos que un profesional debe tener presentes.

Durante esta auditoria no se navego ninguna pagina externa. La revision se hizo inspeccionando codigo fuente, CSV, JSON, notebooks y salidas locales ya existentes en el proyecto.

Las paginas/APIs listadas abajo son las que el proyecto tiene programadas para visitar o consumir.

## 2. Objetivo del proyecto

El proyecto busca estimar y monitorear el valor cuota del AFP Fondo 3 antes o alrededor de la publicacion oficial de la SBS.

En terminos practicos:

1. descarga o consolida datos SBS de valor cuota;
2. descarga factores de mercado;
3. construye retornos y variables explicativas;
4. prueba distintos modelos;
5. selecciona configuraciones con validacion temporal;
6. audita el desempeno en un tramo de prueba;
7. congela una canasta/modelo operativo;
8. genera un monitor HTML para seguimiento diario.

## 3. Paginas, APIs y fuentes detectadas

### 3.1 Paginas SBS

| Fuente | URL | Uso en el proyecto |
|---|---|---|
| Variables SPP SBS | `https://www.sbs.gob.pe/app/spp/variablesSPP_net/PagSS/variables_spp.aspx` | Captura diaria/actual de variables SPP y valores cuota publicados por SBS. |
| Estadisticas SBS | `https://www.sbs.gob.pe/app/stats_net/stats/` | Descarga o inspeccion de historicos mensuales SBS. |
| Portal SPP SBS | `https://www.sbs.gob.pe/app/spp/` | Referencia general y pagina base usada por scripts SBS. |

Scripts relacionados:

- `src/descargar_sbs_actual.py`
- `src/02_inspeccionar_historico_sbs.py`
- `src/03_consolidar_historico_fondo3.py`
- `src/03_consolidar_historico_fondo3_corregido.py`
- `src/80_monitor_sbs_y_validar_pronosticos.py`

### 3.2 Mercado financiero

| Fuente | Metodo | Uso |
|---|---|---|
| Yahoo Finance | libreria `yfinance` | Descarga de precios de ETFs, indices, acciones y factores de mercado. |
| OpenFIGI | `https://api.openfigi.com/v3/mapping` | Enriquecimiento/mapeo de identificadores ISIN/FIGI cuando aplica. |

Scripts relacionados:

- `src/07_descargar_factores_mercado.py`
- `src/35_enriquecer_isin_openfigi.py`
- `src/69_ampliar_universo_factores_y_screening_train.py`
- `src/72_auditar_indices_y_acciones_bvl.py`
- `src/74_ampliar_indices_internacionales_nativos.py`
- `src/76_auditar_futuros_commodities_y_cripto.py`
- `src/86_panel_indicadores_afp_intradia.py`
- `src/92_panel_indicadores_didactico.py`
- `src/99_cuota_sintetica_intradia.py`

### 3.3 Visualizacion

| Fuente | URL | Uso |
|---|---|---|
| Plotly CDN | `https://cdn.plot.ly/plotly-2.35.2.min.js` | Graficos interactivos en monitores HTML. |

### 3.4 Archivos raw locales

Conteo observado en `data/raw/`:

| Carpeta | Archivos |
|---|---:|
| `data/raw/sbs/historico` | 137 |
| `data/raw/sbs/ca0001_composicion` | 133 |
| `data/raw/sbs/fp1356_cartera` | 137 |
| `data/raw/mercados` | 27 |

## 4. Pipeline funcional

El flujo observado es:

```text
SBS y mercado
  -> consolidacion historica SBS
  -> descarga factores mercado
  -> correlaciones y rezagos
  -> base maestra / panel de modelado
  -> competencia de modelos
  -> calibracion y pruebas
  -> canasta final podada
  -> modelo congelado
  -> monitor operativo
```

Ruta por modulos:

| Etapa | Scripts / salidas principales |
|---|---|
| Captura SBS actual | `src/descargar_sbs_actual.py`, `sbs_fondo3_vintages.csv` |
| Historico SBS | `src/02...`, `src/03...`, `sbs_fondo3_historico_largo.csv`, `sbs_fondo3_base_maestra.csv` |
| Factores mercado | `src/07_descargar_factores_mercado.py`, `mercados_factores_*.csv` |
| Correlaciones iniciales | `src/08_analizar_correlaciones_factores.py`, `fondo3_correlaciones_factores_rezagos.csv` |
| Modelos base | `src/09...` a `src/14...` |
| Cartera/composicion | `src/15...` a `src/40...` |
| Competencia y robustez | `src/41...` a `src/68...` |
| Ampliacion de universo | `src/69...` a `src/77...` |
| Canasta final | `src/78_consolidar_y_podar_canasta_final.py` |
| Modelo congelado | `src/79_congelar_modelo_y_estimar_prospectivamente.py` |
| Explicacion de contribuciones | `src/79C_exportar_ecuaciones_exactas_y_contribuciones.py` |
| Monitor | `129_monitor_fondo3_ACTUALIZA_Y_ABRE.py` |

## 5. Division temporal usada

La evidencia esta en:

```text
data/processed/ca0001_modelo50_division_temporal.csv
```

| Segmento | Fechas | Observaciones | Uso |
|---|---|---:|---|
| entrenamiento_descubrimiento | 2015-01-05 a 2021-11-12 | 1779 | seleccionar rezagos y medir correlaciones iniciales |
| validacion | 2021-11-15 a 2024-02-23 | 593 | confirmar estabilidad y elegir regularizacion |
| prueba_intocable | 2024-02-26 a 2026-06-30 | 593 | medir desempeno final sin seleccionar variables |

Esto corresponde aproximadamente a una particion 60% / 20% / 20%.

Punto profesional importante:

- La validacion se uso para escoger modelos/configuraciones.
- La prueba se uso como auditoria.
- Algunos modulos posteriores advierten que la prueba ya fue consultada en varias etapas; por eso la confirmacion definitiva debe hacerse con datos futuros fuera del periodo ya analizado.

## 6. Metodo matematico de correlaciones

### 6.1 Variables usadas

Para AFP:

- `ret_afp`: retorno simple del valor cuota.
- `ret_afp_w`: retorno AFP winsorizado.

Para mercado:

- factores con prefijo `ret_`, por ejemplo `ret_COPX`, `ret_EPU`, `ret_IDX_VIX`.
- rezagos de mercado `lag0`, `lag1`, `lag2`, `lag3`.

### 6.2 Rezagos

Para cada factor de mercado se crean columnas:

```text
factor_lag0, factor_lag1, factor_lag2, factor_lag3
```

Matematicamente:

```text
x_{t, lag k} = x_{t-k}
```

donde `k` pertenece a `{0,1,2,3}`.

### 6.3 Winsorizacion

El proyecto usa winsorizacion al 1% inferior y 1% superior para reducir influencia de valores extremos.

Si `q_0.01` y `q_0.99` son percentiles de la serie:

```text
x_w = min(max(x, q_0.01), q_0.99)
```

No elimina observaciones; recorta extremos.

### 6.4 Correlacion de Pearson

El script `src/08_analizar_correlaciones_factores.py` usa `pandas.Series.corr()` sin especificar metodo, por defecto Pearson.

Formula:

```text
r_xy = cov(x, y) / (sigma_x * sigma_y)
```

equivalentemente:

```text
r_xy = sum((x_i - x_bar)(y_i - y_bar)) /
       sqrt(sum((x_i - x_bar)^2) * sum((y_i - y_bar)^2))
```

Se exige un minimo de 250 observaciones.

### 6.5 Correlacion robusta/winsorizada

El proyecto calcula dos versiones:

```text
correlacion_raw = corr(ret_afp, factor_lag)
correlacion_winsorizada = corr(ret_afp_w, factor_lag_w)
```

Luego elige, para cada AFP y factor, el rezago con mayor:

```text
abs(correlacion_winsorizada)
```

### 6.6 Spearman en auditoria final

En `src/79A_graficos_y_correlaciones_finales.py` tambien se calculan correlaciones Pearson y Spearman entre real y estimado.

Spearman es la correlacion de Pearson aplicada a rangos:

```text
rho = corr(rank(x), rank(y))
```

Sirve para evaluar relacion monotona, menos sensible a escala lineal exacta.

## 7. Resultados de correlaciones

Archivo:

```text
data/processed/fondo3_correlaciones_factores_rezagos.csv
```

Principales correlaciones iniciales winsorizadas observadas:

| AFP | Factor | Correlacion raw | Correlacion winsorizada |
|---|---|---:|---:|
| Profuturo | `ret_IDX_VIX` | -0.4864 | -0.4932 |
| Integra | `ret_IDX_VIX` | -0.4614 | -0.4731 |
| Profuturo | `ret_COPX` | 0.4853 | 0.4626 |
| Integra | `ret_COPX` | 0.4746 | 0.4625 |
| Prima | `ret_COPX` | 0.4892 | 0.4617 |
| Prima | `ret_IDX_VIX` | -0.4666 | -0.4612 |
| Habitat | `ret_COPX` | 0.4679 | 0.4518 |
| Habitat | `ret_IDX_VIX` | -0.4508 | -0.4465 |
| Prima | `ret_EPU` | 0.4602 | 0.4299 |
| Profuturo | `ret_EPU` | 0.4567 | 0.4289 |
| Integra | `ret_EPU` | 0.4442 | 0.4280 |
| Habitat | `ret_EPU` | 0.4404 | 0.4149 |

Lectura:

- `ret_COPX` representa exposicion a cobre/mineria global.
- `ret_IDX_VIX` entra con signo negativo: mayor volatilidad global tiende a asociarse con menor retorno del fondo.
- `ret_EPU` captura Peru ETF, proxy de mercado peruano.
- Correlacion no implica causalidad ni composicion exacta de cartera.

## 8. Modelos evaluados

Se detectan estas familias de modelos:

| Familia | Descripcion |
|---|---|
| OLS / Linear Regression | Regresion lineal ordinaria. |
| Ridge | Regresion lineal con penalizacion L2. |
| ElasticNet | Penalizacion combinada L1/L2. |
| Huber | Regresion robusta frente a outliers. |
| LAD / cuantiles | Regresion robusta por error absoluto/mediana. |
| ARDL | Modelo autoregresivo con rezagos distribuidos. |
| ARIMAX | Modelo ARIMA con variables exogenas. |
| Rolling Ridge | Ridge entrenado con ventana movil. |
| EW-Ridge | Ridge con pesos exponenciales por recencia. |
| Ensambles | Combinacion ponderada de modelos. |
| Calibraciones AFIN/HUBER/IDENTIDAD | Ajustes de amplitud/regimen posteriores. |

## 9. Metodo matematico del modelo final

El modelo operativo final usa `EW_RIDGE`.

### 9.1 Ridge

Ridge estima coeficientes minimizando:

```text
min_beta sum_i (y_i - X_i beta)^2 + alpha * sum_j beta_j^2
```

donde:

- `y_i` es el retorno del valor cuota;
- `X_i` son factores de mercado;
- `beta_j` son coeficientes;
- `alpha` controla regularizacion.

La regularizacion L2 reduce inestabilidad cuando hay factores correlacionados entre si.

### 9.2 Estandarizacion

Antes de ajustar Ridge, las variables se escalan con `StandardScaler`:

```text
z = (x - media) / desviacion
```

Esto evita que variables con mayor escala dominen el ajuste.

### 9.3 Pesos exponenciales

EW-Ridge da mas peso a observaciones recientes.

El peso usado es:

```text
w_i = 0.5 ^ (edad_i / half_life)
```

donde:

- `edad_i = 0` para la observacion mas reciente;
- `half_life` es la vida media;
- cuando la edad es igual a `half_life`, el peso cae a 50%.

Configuracion final:

| AFP | Familia | Alpha | Half-life | Factores |
|---|---|---:|---:|---:|
| Habitat | EW_RIDGE | 0.001 | 60 | 9 |
| Integra | EW_RIDGE | 0.001 | 500 | 4 |
| Prima | EW_RIDGE | 0.001 | 500 | 3 |
| Profuturo | EW_RIDGE | 0.001 | 500 | 5 |

## 10. Seleccion del modelo final

La ruta real hacia el modelo final fue:

```text
modelo50 -> modelo64 -> modelo65 -> modelo66 -> modelo68 -> modelo78 -> modelo79
```

### 10.1 Modelo66

Archivo:

```text
data/processed/ca0001_modelo66_resumen.json
```

Criterio:

```text
Menor MAPE de cuota en validacion; desempate por MAE del retorno acumulado y P90.
```

Ganadores en validacion:

| AFP | Modelo | MAPE validacion |
|---|---|---:|
| Habitat | EW_RIDGE_HL60_A0.001 | 0.7411 |
| Integra | DIARIO_RIDGE | 0.6502 |
| Prima | DIARIO_RIDGE | 0.6111 |
| Profuturo | DIARIO_RIDGE | 0.6223 |

### 10.2 Modelo68

Aplica calibracion de amplitud/regimen.

| AFP | Calibracion | MAPE validacion |
|---|---|---:|
| Habitat | AFIN_W250 | 0.5449 |
| Integra | IDENTIDAD_EW | 0.4659 |
| Prima | IDENTIDAD_EW | 0.4466 |
| Profuturo | HUBER_W120 | 0.4857 |

### 10.3 Modelo78

Consolida y poda la canasta final.

Criterio documentado en `ca0001_modelo78_resumen.json`:

```text
Solo se heredan cambios de modulos con mejora favorable en Diebold-Mariano.
Despues se realiza poda backward usando exclusivamente validacion.
La prueba se usa solo como auditoria.
```

### 10.4 Modelo79

Congela el modelo prospectivo:

- no vuelve a seleccionar variables cada dia;
- usa canasta final podada de modulo 78;
- genera manifiesto reproducible;
- produce pronosticos prospectivos.

Archivos:

- `data/processed/ca0001_modelo79_manifiesto_modelo_congelado.json`
- `data/processed/ca0001_modelo79_canasta_congelada.csv`
- `data/processed/ca0001_modelo79_primer_pronostico_congelado.csv`

## 11. Metricas usadas

### 11.1 MAE

Error absoluto medio:

```text
MAE = mean(|y - y_hat|)
```

### 11.2 RMSE

Raiz del error cuadratico medio:

```text
RMSE = sqrt(mean((y - y_hat)^2))
```

Penaliza mas los errores grandes.

### 11.3 R2

Coeficiente de determinacion:

```text
R2 = 1 - sum((y - y_hat)^2) / sum((y - y_bar)^2)
```

### 11.4 MAPE de cuota

Error porcentual absoluto medio sobre valor cuota:

```text
MAPE = mean(|cuota_real - cuota_estimada| / cuota_real) * 100
```

### 11.5 P90 de error absoluto

Percentil 90 del error absoluto porcentual:

```text
P90 = quantile(error_abs_pct, 0.90)
```

Sirve para ver errores altos, no solo promedio.

### 11.6 Direccion acumulada

Porcentaje de veces que el signo del retorno estimado coincide con el signo real:

```text
direccion = mean(sign(ret_real) == sign(ret_estimado)) * 100
```

### 11.7 Diebold-Mariano y Holm

El proyecto usa pruebas Diebold-Mariano para comparar perdida predictiva entre modelos. La idea es contrastar si una serie de errores tiene perdida promedio significativamente menor que otra.

La correccion Holm se menciona para ajustar multiples comparaciones y reducir falsos positivos.

## 12. Resultados finales auditados

Archivo:

```text
data/processed/ca0001_modelo78_metricas_prueba.csv
```

Filtro usado:

```text
tipo_modelo = CANASTA_PODADA
```

| AFP | Factores | Familia | Alpha | Half-life | MAPE prueba | P90 error | R2 diario | Direccion acumulada |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| Habitat | 9 | EW_RIDGE | 0.001 | 60 | 0.6381 | 1.4690 | 0.5457 | 83.64% |
| Integra | 4 | EW_RIDGE | 0.001 | 500 | 0.7188 | 1.7297 | 0.4982 | 79.76% |
| Prima | 3 | EW_RIDGE | 0.001 | 500 | 0.7831 | 1.9225 | 0.4660 | 81.28% |
| Profuturo | 5 | EW_RIDGE | 0.001 | 500 | 0.7513 | 1.8233 | 0.4638 | 82.80% |

Correlaciones finales entre real y estimado:

Archivo:

```text
data/processed/ca0001_modelo79a_correlaciones_finales.csv
```

| AFP | Pearson cuota | Spearman cuota | Pearson retorno acumulado | Spearman retorno acumulado | MAPE | Direccion |
|---|---:|---:|---:|---:|---:|---:|
| Habitat | 0.9975 | 0.9855 | 0.8477 | 0.8216 | 0.6381 | 83.64% |
| Integra | 0.9955 | 0.9825 | 0.8030 | 0.7933 | 0.7188 | 79.76% |
| Prima | 0.9939 | 0.9825 | 0.7880 | 0.7915 | 0.7831 | 81.28% |
| Profuturo | 0.9943 | 0.9857 | 0.8144 | 0.8241 | 0.7513 | 82.80% |

Advertencia profesional:

La correlacion de cuota puede ser muy alta porque las cuotas son series de nivel con tendencia. La correlacion sobre retornos acumulados, MAPE, P90 y direccion son mas informativas para evaluar prediccion.

## 13. Que muestra el monitor

El monitor principal se genera con:

```text
129_monitor_fondo3_ACTUALIZA_Y_ABRE.py
```

Salida:

```text
data/processed/ca0001_monitor_fondo3_actualizado.html
```

El monitor prioriza la serie historica del modelo desde:

```text
data/processed/ca0001_modelo78_simulacion_publicacion_5d.csv
```

Por eso la linea historica del monitor puede diferir de graficos que usen `modelo66`, que era una etapa intermedia.

## 14. Limitaciones

1. Correlacion no implica causalidad.
2. La composicion real de cartera no se conoce a frecuencia diaria con la misma granularidad de mercado.
3. La prueba 2024-02-26 a 2026-06-30 fue usada como auditoria, pero varios modulos posteriores la consultaron; la validacion definitiva debe hacerse con datos futuros.
4. Yahoo Finance/yfinance puede tener ajustes, faltantes o cambios de proveedor.
5. El monitor depende de archivos locales procesados; si una fuente cambia formato, los scripts de descarga pueden requerir ajuste.
6. La alta correlacion de cuotas en niveles debe interpretarse con cautela; es preferible mirar retornos, MAPE, P90 y direccion.

## 15. Conclusion profesional

El proyecto tiene una estructura cuantitativa razonable para un nowcasting operativo:

- fuentes oficiales SBS;
- factores de mercado externos;
- seleccion temporal 60/20/20;
- correlaciones con rezagos y winsorizacion;
- modelos lineales, robustos, dinamicos y ponderados;
- seleccion por validacion;
- auditoria por prueba;
- congelamiento operativo del modelo final;
- monitor reproducible.

El modelo final no es simplemente el primer ganador de una competencia de modelos. Es el resultado de una cadena de seleccion, calibracion, poda y congelamiento:

```text
modelo50 -> modelo64/65/66 -> modelo68 -> modelo78 -> modelo79 -> monitor
```

Para presentar el proyecto a un profesional externo, los archivos mas importantes son:

- `docs/05_auditoria_modelo_final.md`
- `docs/06_auditoria_tecnica_profesional.md`
- `notebooks/02_desarrollo_modelo_fondo3_paso_a_paso.ipynb`
- `data/processed/ca0001_modelo50_division_temporal.csv`
- `data/processed/ca0001_modelo78_metricas_prueba.csv`
- `data/processed/ca0001_modelo79_manifiesto_modelo_congelado.json`
- `data/processed/ca0001_modelo79_canasta_congelada.csv`
