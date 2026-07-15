# Resultados iniciales del modelo de salida T+1

Fecha de ejecución: 15 de julio de 2026.

## Diseño evaluado

- División cronológica: 60% entrenamiento, 20% validación y 20% test reservado.
- Objetivo: probabilidad de que la siguiente cuota SBS disponible sea menor.
- Modelos candidatos: regresión logística y Gradient Boosting.
- Modelo y umbral elegidos únicamente con validación.
- Auditoría walk-forward expansiva con reentrenamiento cada 20 observaciones.
- Regla de publicación: para decidir en la fecha `t`, solo se incorporan al entrenamiento filas cuya fecha objetivo sea estrictamente anterior a `t`.

## Resultado walk-forward

| AFP | AUC | Precisión de alerta | Cobertura de caídas | Alertas | Mejora de precisión frente a prevalencia | Estado |
|---|---:|---:|---:|---:|---:|---|
| Habitat | 0.5533 | 54.55% | 14.12% | 66 | +11.69 pp | No aprobado |
| Integra | 0.5079 | 0.00% | 0.00% | 3 | -44.03 pp | No aprobado |
| Prima | 0.5130 | 47.06% | 3.04% | 17 | +2.86 pp | No aprobado |
| Profuturo | 0.5062 | 40.00% | 3.76% | 25 | -4.71 pp | No aprobado |

## Interpretación

Ninguna AFP cumplió todos los criterios de aprobación. Habitat mostró una señal débil: mejoró la precisión respecto de la prevalencia y superó ligeramente el AUC mínimo, pero solo detectó 14.12% de las caídas. Esa cobertura es insuficiente para presentarlo como sistema de protección.

Integra, Prima y Profuturo tuvieron AUC cercano a 0.50 y no demostraron capacidad estable para anticipar la siguiente caída.

## Decisión técnica

- No integrar estas señales al monitor operativo.
- No mostrar `RIESGO ALTO` como una señal validada.
- Mantener el modelo como experimento reproducible.
- La siguiente versión debe reducir variables, usar modelos más simples y evaluar específicamente pérdidas relevantes o reversión después de un rebote, en lugar de intentar clasificar cualquier variación negativa diaria.

Estos resultados son una evaluación estadística experimental y no constituyen una recomendación financiera.
