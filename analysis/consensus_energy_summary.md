# Prueba de consenso y candidatos adicionales — 2026-08-31

No modifica el visor ni las ecuaciones oficiales. Modelo base: Retornos v2-sbs-corrected-20260831. Entrenamiento 07/07/2026–17/08/2026; OOS disponible: 7 ruedas posteriores con SBS.

## 1. Regla de consenso para divergencias

Confirmadores US (SPY–QQQ): EEM, MCHI, EPU, SPBLSCUP, NEM y FCX. Se activa la corrección de signo existente solo cuando uno de SPY/QQQ queda alineado con la mayoría y el otro queda como outlier.

- Consenso >=3 o >=4 confirmadores: PRE n=7, 4 mejora / 3 empeora; MAE 0.34732 -> 0.33970 pp (+2.19%), RMSE +6.86%. TRAIN n=5, 4/1; MAE +5.67%. OOS: 19/08 fue el único caso, y empeoró 1.34%.
- Consenso >=5: PRE igual; TRAIN n=2, 1/1, MAE sin mejora; OOS 19/08 empeora.
- Consenso 6/6: PRE n=2, ambos empeoran; TRAIN n=1, empeora; OOS 19/08 empeora.

Conclusión US: aumentar el consenso no resuelve por sí solo SPY–QQQ. El caso 19/08 muestra que si QQQ es el aislado débil pero el resto del mercado está fuerte, una corrección negativa no debe activarse automáticamente. La regla debe ser asimétrica y considerar cuál indicador es el outlier y la dirección del resto del mercado.

Confirmadores PE (EPU–SPBLSCUP): SPY, QQQ, EEM, MCHI, NEM y FCX.

- Consenso >=3 o >=4: PRE n=11, 7 mejora / 4 empeora; MAE 0.72964 -> 0.72078 pp (+1.21%), RMSE +1.20%. TRAIN n=2, ambos mejoran (muestra muy pequeña). OOS: 24/08 mejora 11.10%.
- Consenso >=5: PRE n=11, 7/4; TRAIN n=1, mejora; sin caso OOS.
- Consenso 6/6: PRE n=3, 1/2 y empeora MAE 3.31%; sin casos recientes suficientes.

Conclusión PE: el consenso moderado 3–4 de 6 es más prometedor que exigir unanimidad, pero todavía hay pocos OOS.

## 2. Candidatos adicionales como overlay del modelo base

Se estimó gamma sobre el residual del modelo en 07/07–17/08 y se aplicó al modelo congelado. El entrenamiento se evaluó leave-one-out.

| Candidato | Train LOO MAE | PRE MAE | OOS MAE |
|---|---:|---:|---:|
| NEM | -6.63% | +4.57% | +7.06% |
| USD/PEN | -1.84% | -2.98% | +4.30% |
| COP | -4.66% | -0.13% | +2.89% |
| USO | -3.66% | +0.05% | +2.21% |
| XOP | -4.40% | -0.08% | +2.01% |
| XLE | -4.16% | -0.32% | +1.49% |
| EPU | -2.10% | +0.96% | +0.71% |
| XOM | -4.68% | -0.89% | -0.58% |
| FCX | -4.31% | +1.72% | -3.86% |

Un valor positivo significa reducción del MAE; negativo, empeoramiento. Ningún candidato mejora el LOO del entrenamiento reciente como overlay lineal permanente. NEM es el único que mejora tanto PRE como OOS, aunque empeora el LOO del período de entrenamiento; por ello es candidato de investigación, no sustitución automática.

## 3. Reestimación OLS agregando un sexto factor

Comparación justa: regresión base de cinco retornos vs la misma regresión + un candidato, ambas calibradas en las mismas 30 ruedas y evaluadas en las 7 OOS.

| Sexto factor | Mejora MAE OOS | Mejora RMSE OOS |
|---|---:|---:|
| NEM | +17.66% | +5.82% |
| USD/PEN | +9.70% | +4.71% |
| COP | +5.26% | +4.49% |
| USO | +4.72% | +4.20% |
| XOM | +4.60% | +1.04% |
| XLE | +3.28% | +3.70% |
| XOP | +3.07% | +3.62% |
| EPU | +1.56% | -7.87% |
| FCX | -9.40% | -19.06% |

Con solo 7 OOS estos porcentajes son exploratorios. NEM destaca por encima de energía. Entre los proxies de energía, COP y USO son los mejores en esta muestra; XLE mejora, pero menos.

## Recomendación de prueba

1. Mantener las cinco variables oficiales sin cambios.
2. Usar divergencias como capa de shock, no como corrección diaria.
3. Para EPU–SPBLSCUP seguir observando consenso 3–4/6.
4. Para SPY–QQQ usar una regla asimétrica que descarte el caso “QQQ débil aislado / resto fuerte”; no usar 6/6 ni Z alto por sí solos.
5. Abrir dos challengers en sombra: base + NEM y base + energía. Para energía priorizar USO (precio del petróleo) y COP (equity de productor) antes que XLE; comparar al menos 20–30 nuevas OOS antes de decidir.
