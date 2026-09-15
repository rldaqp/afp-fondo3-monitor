# Modelo experimental de salida 60/20/20

## Propósito

Este desarrollo no reemplaza el nowcast operativo. Su objetivo es estimar el riesgo de que la siguiente cuota SBS disponible sea menor que la cuota estimada al momento de decidir, con énfasis en proteger una ganancia ya acumulada.

## Separación respecto del modelo actual

- **Nowcast vigente:** estima una cuota cuya jornada de mercado ya ocurrió, pero que la SBS todavía no publicó.
- **Modelo de salida:** utiliza la información conocida al cierre de la fecha `t` para anticipar la siguiente cuota disponible `t+1`.

No deben mezclarse sus métricas. Un buen resultado del nowcast no demuestra que exista capacidad para predecir la siguiente jornada.

## Unidad de observación

Cada fila representa una combinación de:

```text
fecha de decisión + AFP
```

La fila solo puede contener información disponible en esa fecha. El objetivo se desplaza hacia la siguiente fecha SBS disponible.

## Datos iniciales

1. Cuota SBS oficial y retorno diario.
2. Retorno estimado por el nowcast disponible al decidir.
3. Diferencia entre cuota estimada y última cuota SBS.
4. Retornos de los factores de la canasta por AFP.
5. Momentum de 2, 3 y 5 jornadas.
6. Volatilidad de 5, 10 y 20 jornadas.
7. Aceleración o desaceleración del retorno estimado.
8. Amplitud ponderada de factores positivos y negativos.
9. Máximo reciente, ganancia acumulada y retroceso desde el máximo.
10. Error reciente del nowcast cuando la cuota SBS posterior ya está disponible.

Las variables personales de una operación —cuota de entrada, número de cuotas y saldo— se usarán en el simulador de posición. El entrenamiento principal se hará con variables de mercado y cuota para que la señal sea reproducible en todas las fechas.

## Objetivos

### Objetivo de regresión

```text
retorno_real_t1 = cuota_sbs_t1 / cuota_sbs_t - 1
```

### Objetivo de clasificación

```text
caida_t1 = 1 cuando retorno_real_t1 < 0; 0 en caso contrario
```

### Objetivo de control de riesgo

Evaluar si una alerta habría reducido el retroceso desde el máximo, descontando el crecimiento sacrificado por alertas demasiado tempranas.

## División temporal

- Primer 60%: entrenamiento.
- Siguiente 20%: selección de modelos, variables y umbrales.
- Último 20%: test reservado.

Las fechas no se barajan. Después de esta auditoría se añadirá una simulación walk-forward que congele cada señal antes de conocer la cuota SBS siguiente.

## Modelos de la primera versión

1. Regresión logística: referencia estable y explicable.
2. Gradient Boosting: candidato no lineal.
3. Ensamble: solo se habilitará si mejora de forma estable la validación sin deteriorar el test reservado.

## Métricas prioritarias

- Precisión de alertas de riesgo.
- Cobertura de caídas.
- Tasa de falsas alarmas.
- Brier score para probabilidades.
- Ganancia sacrificada por salida temprana.
- Retroceso que habría podido evitarse.
- Máximo retroceso de la estrategia simulada.
- Estabilidad por AFP y por periodo.

La exactitud global no será suficiente: un modelo que siempre diga “continuidad” puede parecer correcto si las caídas son poco frecuentes, pero no protegería el capital.

## Estados del tablero

- `CONTINUIDAD`: impulso favorable y riesgo siguiente bajo.
- `VIGILANCIA`: pérdida de fuerza, divergencias o aumento de volatilidad.
- `RIESGO_ALTO`: probabilidad elevada de caída y evidencia adicional de retroceso o desaceleración.
- `SIN_SENAL`: modelos contradictorios, datos incompletos o incertidumbre excesiva.

## Regla de seguridad del desarrollo

Durante la fase experimental:

- no se modifica la canasta congelada;
- no se reemplaza el nowcast vigente;
- no se elimina ningún archivo operativo;
- no se integra el nuevo modelo al flujo principal hasta validar que ejecuta correctamente y produce resultados auditables;
- cada pronóstico futuro deberá conservarse antes de conocer la SBS.
