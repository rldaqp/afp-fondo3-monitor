# Simulación del desfase real de publicación

La estimación parte de la última cuota que habría estado disponible y acumula los retornos predichos de los siguientes 4 o 5 días de observación.

Los días se cuentan como observaciones consecutivas de la serie SBS/mercado, no como días calendario. Esto evita tratar fines de semana y feriados como sesiones con retorno.

## Habitat

- Desfase 4 días: MAPE=1.030 %, error P90=2.471 %, dirección=74.5 %, correlación acumulada=0.642.
- Desfase 5 días: MAPE=1.179 %, error P90=2.946 %, dirección=74.0 %, correlación acumulada=0.643.

## Integra

- Desfase 4 días: MAPE=1.133 %, error P90=2.807 %, dirección=68.8 %, correlación acumulada=0.597.
- Desfase 5 días: MAPE=1.286 %, error P90=3.209 %, dirección=67.2 %, correlación acumulada=0.598.

## Prima

- Desfase 4 días: MAPE=1.071 %, error P90=2.599 %, dirección=75.4 %, correlación acumulada=0.619.
- Desfase 5 días: MAPE=1.226 %, error P90=3.241 %, dirección=72.9 %, correlación acumulada=0.612.

## Profuturo

- Desfase 4 días: MAPE=1.192 %, error P90=2.844 %, dirección=69.3 %, correlación acumulada=0.643.
- Desfase 5 días: MAPE=1.359 %, error P90=3.131 %, dirección=68.3 %, correlación acumulada=0.644.

## Interpretación

Esta simulación es más cercana al uso real que una estimación de un solo día, porque reproduce el periodo durante el cual la SBS todavía no habría publicado las cuotas recientes.
La estimación debe reanclarse cada vez que aparece una nueva cuota oficial. No debe acumularse indefinidamente.