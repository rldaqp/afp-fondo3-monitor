# Reporte operativo AFP Fondo 3 — 2026-07-03

## Estado general

- Estado: **VALIDADO_DEBIL**
- Dirección común: **positiva**
- Intensidad: **debil**
- Diferenciación entre AFP: **baja**
- Modelo operativo: **M0_base_mercado**
- Composición CA-0001 utilizada: **No**

## Nowcast por AFP

| AFP | Estimador | Retorno estimado | Ratio / RMSE | Lectura |
|---|---|---:|---:|---|
| Habitat | ElasticNet | 0.1265% | 0.296 | debil_frente_al_error_oos |
| Integra | Huber_robusto | 0.1062% | 0.251 | debil_frente_al_error_oos |
| Prima | Huber_robusto | 0.1021% | 0.231 | debil_frente_al_error_oos |
| Profuturo | Huber_robusto | 0.1135% | 0.272 | debil_frente_al_error_oos |

## Lectura ejecutiva

Sesgo positivo débil y homogéneo; sin diferenciación estadística suficiente entre AFP y sin señal fuerte por sí sola.

## Tendencia disponible

| Fecha | Retorno medio | AFP positivas | AFP negativas | Dispersión |
|---|---:|---:|---:|---:|
| 2026-07-01 | -0.4440% | 0 | 4 | 0.1886 pp |
| 2026-07-02 | 0.0429% | 4 | 0 | 0.0311 pp |
| 2026-07-03 | 0.1121% | 4 | 0 | 0.0244 pp |

## Alertas

- **SENAL_DEBIL**: La predicción mediana equivale a 0.262 veces el RMSE OOS.
- **BAJA_DIFERENCIACION_AFP**: La dispersión entre AFP es 0.0244 puntos porcentuales.
- **COMPOSICION_VENCIDA**: 4 AFP operan con fallback M0_base_mercado.

## Nota metodológica

Este reporte es un diagnóstico estadístico. No constituye una recomendación de compra, venta, cambio de fondo o decisión financiera.
