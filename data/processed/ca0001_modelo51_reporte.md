# Canasta depurada para seguimiento del Fondo 3

## Criterio

Se eliminaron duplicados exactos y factores con información muy redundante. La canasta se seleccionó con entrenamiento y validación; la prueba final se usó solo para evaluar.

## Núcleo común

- **ret_COPX** — ETF de mineras de cobre; aparece en 4 AFP; rezago más frecuente: 0 días.
- **ret_EPU** — ETF de acciones peruanas; aparece en 3 AFP; rezago más frecuente: 0 días.

## Habitat

1. **ret_IDX_VIX** — Índice de volatilidad VIX; relación negativa; lag 0; correlación de prueba -0.485.
2. **ret_COPX** — ETF de mineras de cobre; relación positiva; lag 0; correlación de prueba 0.503.

Prueba final: R²=0.377; dirección correcta=69.5 %; mejora RMSE frente a cero=21.2 %.

## Integra

1. **ret_COPX** — ETF de mineras de cobre; relación positiva; lag 0; correlación de prueba 0.528.
2. **ret_EPU** — ETF de acciones peruanas; relación positiva; lag 0; correlación de prueba 0.501.

Prueba final: R²=0.299; dirección correcta=68.7 %; mejora RMSE frente a cero=16.3 %.

## Prima

1. **ret_COPX** — ETF de mineras de cobre; relación positiva; lag 0; correlación de prueba 0.528.
2. **ret_EPU** — ETF de acciones peruanas; relación positiva; lag 0; correlación de prueba 0.494.
3. **ret_IDX_VIX** — Índice de volatilidad VIX; relación negativa; lag 0; correlación de prueba -0.504.
4. **ret_XLB** — ETF del sector materiales de Estados Unidos; relación positiva; lag 0; correlación de prueba 0.300.

Prueba final: R²=0.402; dirección correcta=72.8 %; mejora RMSE frente a cero=22.7 %.

## Profuturo

1. **ret_COPX** — ETF de mineras de cobre; relación positiva; lag 0; correlación de prueba 0.523.
2. **ret_EPU** — ETF de acciones peruanas; relación positiva; lag 0; correlación de prueba 0.500.

Prueba final: R²=0.299; dirección correcta=68.9 %; mejora RMSE frente a cero=16.3 %.

## Advertencia interpretativa

Los ETF e índices seleccionados son termómetros públicos de la exposición económica observada. No prueban que la AFP mantenga exactamente esos instrumentos en cartera.