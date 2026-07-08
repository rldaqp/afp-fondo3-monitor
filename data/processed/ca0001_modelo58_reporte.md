# Archivo y validación automática de estimaciones

El módulo archiva las estimaciones y su cobertura de factores generadas por el módulo 57 antes de que sean reemplazadas. Cuando la SBS incorpora la cuota de una fecha estimada, el pronóstico pasa de PENDIENTE a VALIDADO.

## Nuevas validaciones

- Pronósticos recién validados: 0.
- Pronósticos todavía pendientes: 12.

## Métricas

### Habitat — primera_prediccion

- Observaciones validadas: 0.

### Integra — primera_prediccion

- Observaciones validadas: 0.

### Prima — primera_prediccion

- Observaciones validadas: 0.

### Profuturo — primera_prediccion

- Observaciones validadas: 0.

### Habitat — ultima_prediccion

- Observaciones validadas: 0.

### Integra — ultima_prediccion

- Observaciones validadas: 0.

### Prima — ultima_prediccion

- Observaciones validadas: 0.

### Profuturo — ultima_prediccion

- Observaciones validadas: 0.

## Reconciliación de contribuciones

La contribución total incluye COPX, EPU, VIX o XLB, según la AFP, más el intercepto del modelo.
- Filas reconciliadas: 12 de 12.

## Regla operativa

Ejecute este módulo inmediatamente después del módulo 57 para archivar los pronósticos. Cuando actualice las cuotas SBS, vuelva a ejecutar primero el módulo 58 para validar las predicciones anteriores y después ejecute nuevamente el 57.