# Proyecto: valor cuota intradia por cartera replicante

## Objetivo

Construir una estimacion intradia del valor cuota del Fondo 3 usando la cartera real publicada por la SBS y precios de mercado de los instrumentos que componen esa cartera.

La idea no es afirmar que existe una cuota SBS intradia. La idea es aproximar como podria moverse el valor cuota durante el dia si valorizamos la ultima cartera publica disponible con precios intradia.

## Modelo principal

El modelo base es una cartera replicante:

```text
retorno_estimado_fondo(t) =
  peso_1 * retorno_activo_1(t)
+ peso_2 * retorno_activo_2(t)
+ peso_3 * retorno_activo_3(t)
+ ...
+ efecto_tipo_cambio(t)
+ retorno_activos_sin_precio(t)
```

Luego:

```text
valor_cuota_estimado(t) =
ultima_cuota_SBS * (1 + retorno_estimado_fondo(t))
```

Donde:

- `peso_i` viene de la cartera publicada por SBS.
- `retorno_activo_i(t)` viene de la cotizacion intradia del instrumento o de un proxy.
- `ultima_cuota_SBS` es la ultima cuota oficial disponible.

## Modelo de ajuste

Como la cartera SBS puede publicarse con rezago y algunos instrumentos no tienen precio intradia, se agrega una capa de ajuste.

Primera version:

```text
error_diario =
retorno_real_SBS - retorno_cartera_replicante
```

Y se entrena un ajuste simple:

```text
error_estimado =
Ridge(factores_de_error)
```

Valor final:

```text
retorno_final_estimado =
retorno_cartera_replicante + error_estimado
```

Version avanzada futura:

```text
Kalman Filter
```

Ese modelo trataria al valor cuota intradia como una variable no observable que se actualiza cada vez que llegan precios de mercado.

## Informacion necesaria

### SBS

Se usa para:

- valor cuota oficial del Fondo 3;
- cartera especifica por AFP y fondo;
- pesos por instrumento;
- fecha de cartera disponible;
- patrimonio o monto total del fondo cuando este disponible.

Archivos actuales del repositorio:

- `data/processed/ca0001_fondo3_hoja10_base_canonica_reconciliada.csv`
- `data/processed/ca0001_fondo3_hoja10_base_modelo_principal.csv`
- `data/processed/ca0001_fondo3_historico_top_ultimo_mes.csv`
- `data/processed/sbs_fondo3_base_maestra.csv`

### Mercado

Se usa para precios intradia:

- Yahoo Finance / yfinance;
- Stooq;
- BVL;
- fuente de tipo de cambio USD/PEN;
- fuente futura de bonos o proxies de renta fija.

## Salidas esperadas

El proyecto debe producir:

- cartera replicante por AFP;
- tabla de instrumentos con peso y fuente de precio;
- estimaciones intradia cada 15 minutos;
- velas intradia de valor cuota estimado;
- evaluacion historica contra SBS;
- metricas por AFP y por hora del dia.

## Metricas

### Precision diaria

```text
MAE = error absoluto promedio
RMSE = error cuadratico promedio
MAPE = error porcentual promedio
Correlacion = relacion entre retorno estimado y retorno real
Acierto direccion = porcentaje de dias donde acierta sube/baja
Tracking error = desviacion estandar del error
```

### Utilidad intradia

```text
Error 10:00 vs cuota SBS final
Error 12:00 vs cuota SBS final
Error 15:00 vs cuota SBS final
Error cierre vs cuota SBS final
```

Esto permite responder:

```text
A que hora del dia la estimacion empieza a ser util?
```

### Comparacion contra modelos simples

El modelo debe superar:

```text
cuota manana = ultima cuota SBS
retorno esperado = 0
modelo actual por indices/proxies
```

## Fases

1. Preparar base de cartera real SBS.
2. Mapear instrumentos a ticker o proxy.
3. Descargar precios intradia.
4. Calcular valor cuota estimado intradia.
5. Construir velas cada 15 minutos.
6. Comparar contra cuota SBS cuando se publique.
7. Entrenar modelo de ajuste.
8. Publicar vista en GitHub Pages.

## Regla de interpretacion

La interfaz debe decir:

```text
Valor cuota intradia estimado con la ultima cartera publica disponible.
```

No debe decir:

```text
Valor cuota oficial intradia.
```

