# Simulación correcta del retraso de publicación de la SBS

Para cada fecha histórica tratada como “hoy”, el sistema supone que solo están visibles las cuotas cuya fecha es al menos cinco días calendario anterior. Las cuotas más recientes se estiman con los activos seleccionados en el módulo 51.

## Resultados por AFP

### Habitat

- Activos de seguimiento: ret_IDX_VIX | ret_COPX.
- Error porcentual absoluto medio: 0.886 %.
- Dirección acumulada correcta: 72.1 %.
- Correlación del movimiento acumulado: 0.622.
- Cuotas ocultas estimadas por ventana: 2 a 5.
- Última simulación: el 2026-06-30 solo habría estado visible la cuota del 2026-06-25.
- Cuota estimada: 33.571477; cuota posteriormente observada: 33.537063.

### Integra

- Activos de seguimiento: ret_COPX | ret_EPU.
- Error porcentual absoluto medio: 0.971 %.
- Dirección acumulada correcta: 69.0 %.
- Correlación del movimiento acumulado: 0.587.
- Cuotas ocultas estimadas por ventana: 2 a 5.
- Última simulación: el 2026-06-30 solo habría estado visible la cuota del 2026-06-25.
- Cuota estimada: 72.344411; cuota posteriormente observada: 72.328460.

### Prima

- Activos de seguimiento: ret_COPX | ret_EPU | ret_IDX_VIX | ret_XLB.
- Error porcentual absoluto medio: 0.957 %.
- Dirección acumulada correcta: 73.8 %.
- Correlación del movimiento acumulado: 0.594.
- Cuotas ocultas estimadas por ventana: 2 a 5.
- Última simulación: el 2026-06-30 solo habría estado visible la cuota del 2026-06-25.
- Cuota estimada: 65.740060; cuota posteriormente observada: 65.791816.

### Profuturo

- Activos de seguimiento: ret_COPX | ret_EPU.
- Error porcentual absoluto medio: 1.013 %.
- Dirección acumulada correcta: 69.8 %.
- Correlación del movimiento acumulado: 0.614.
- Cuotas ocultas estimadas por ventana: 2 a 5.
- Última simulación: el 2026-06-30 solo habría estado visible la cuota del 2026-06-25.
- Cuota estimada: 71.793060; cuota posteriormente observada: 71.934830.

## Interpretación

La prueba ya no exige que la SBS y los ETF compartan exactamente el mismo calendario. Cada valor cuota se alinea con el último cierre disponible de cada factor.
La estimación se reancla en la última cuota que habría estado publicada. La cuota real del día objetivo se mantiene oculta durante el cálculo y se usa únicamente para medir el error.