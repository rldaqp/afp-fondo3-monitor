# Auditoria de archivos - AFP Fondo 3

Ruta auditada: `E:\Mi unidad (rldaqp@gmail.com)\01. DSIS OEFA\afp_fondo3_inicio\afp_fondo3_inicio`

Fecha de auditoria: 2026-07-06

> No se borro ni movio ningun archivo. Este reporte solo crea una clasificacion para decidir limpieza posterior.

## Resumen ejecutivo

- Total de archivos revisados: **1599**
- Mantener: **257**
- Mover a archivo: **793**
- No tocar: **525**
- Posible eliminar: **24**
- Grupos de duplicados exactos por SHA256: **16**

## Criterios usados

- **Mantener**: codigo fuente activo, lanzadores operativos, automatizaciones vigentes, documentacion y salidas finales usadas por monitores/modelos.
- **Mover a archivo**: versiones antiguas, respaldos, scripts raiz reemplazados por `src/`, resultados experimentales, graficos, logs y salidas historicas no operativas.
- **Posible eliminar**: caches, checkpoints, `.pyc`, `.bak`, copias exactas marcadas `(1)` o salidas generadas duplicadas. Validar uso antes de borrar.
- **No tocar**: datos raw, historicos, bases canonicas y modelos entrenados que preservan trazabilidad o reproducibilidad.

## Hallazgos principales

- El proyecto no tiene `.git`; no hay historial de versiones formal. Conviene archivar antes de limpiar.
- Hay muchos scripts numerados en la raiz que parecen instaladores/correcciones sucesivas; la version operativa deberia vivir en `src/` y los scripts raiz deberian archivarse salvo lanzadores manuales.
- Hay duplicados exactos en `src/`: `57/58/59/60` con copias `(1)`, backups de simuladores `97/105`, y `80_monitor...` duplicado entre raiz y `src/`.
- `data/raw/` y bases historicas/procesadas deben preservarse: son la evidencia para backtesting y auditoria.
- `__pycache__`, `.pyc`, `.ipynb_checkpoints` y `.bak` son candidatos claros a limpieza despues de confirmar que no se necesitan como evidencia.

## Archivos esenciales

Principales grupos que sostienen el proyecto:

- `README.md`, `requirements.txt`
- `src/*.py` sin marcas `BACKUP`, `RESPALDO`, `(1)` ni instaladores puntuales
- `automatizacion/*.bat` y `automatizacion/*.vbs` operativos
- lanzadores manuales actuales: `EJECUTAR_FONDO3.bat`, `ACTUALIZAR_Y_ABRIR_MONITOR_FONDO3.bat`, `ABRIR_MONITOR_PRACTICO_FONDO3.bat`, `ABRIR_MONITOR_SIMPLE_FONDO3.bat`, `SIMULAR ...`, `VER ...`
- salidas finales/actuales en `data/processed/` usadas por monitores y modelos

## Versiones antiguas

Patrones detectados para archivar: `BACKUP_...`, `RESPALDO_...`, `(1)`, `_V117` a `_V128`, `dashboard_anterior`, scripts de instalacion/correccion puntuales y scripts numerados en la raiz reemplazados por `src/`.

## Duplicados exactos

| Grupo | Archivos | Hash corto |
|---:|---:|---|
| 1 | 8 | `F01A374E9C81` |
| 2 | 2 | `5E0C4B544D74` |
| 3 | 2 | `018E683F215F` |
| 4 | 2 | `F1CB2B694532` |
| 5 | 2 | `C43D3B679067` |
| 6 | 2 | `E093D0EC5F35` |
| 7 | 2 | `1E542E0282F8` |
| 8 | 2 | `A1AD85EF85E5` |
| 9 | 2 | `3AA660D0A3C5` |
| 10 | 2 | `EAD80EE6F67C` |
| 11 | 2 | `0D8A74DBA642` |
| 12 | 2 | `EE70D171A44A` |
| 13 | 2 | `26D9476C4741` |
| 14 | 2 | `074B53E0E861` |
| 15 | 2 | `E15FA0A85895` |
| 16 | 2 | `7A0E0068704E` |

### Grupo 1 - duplicado exacto

- `data/processed/ca0001_errores_inspeccion.csv`
- `data/processed/ca0001_fondo3_historico_errores.csv`
- `data/processed/ca0001_modelo76_factores_casi_duplicados.csv`
- `data/processed/ca0001_piloto_fondo3_errores.csv`
- `data/processed/fp1356_errores_inspeccion.csv`
- `data/processed/fp1356_fondo3_errores.csv`
- `data/processed/mercados_errores_descarga.csv`
- `data/processed/sbs_fondo3_errores.csv`

### Grupo 2 - duplicado exacto

- `src/105_simulador_periodo_y_velas_fondo3_BACKUP_20260705_170742.py`
- `src/97_simulador_monto_fondo3_BACKUP_20260705_170742.py`

### Grupo 3 - duplicado exacto

- `src/105_simulador_periodo_y_velas_fondo3_BACKUP_20260705_164739.py`
- `src/97_simulador_monto_fondo3_BACKUP_20260705_164739.py`

### Grupo 4 - duplicado exacto

- `src/105_simulador_periodo_y_velas_fondo3_BACKUP_20260705_163529.py`
- `src/97_simulador_monto_fondo3_BACKUP_20260705_163529.py`

### Grupo 5 - duplicado exacto

- `src/57_generar_seguimiento_operativo_y_grafica_actual(1).py`
- `src/57_generar_seguimiento_operativo_y_grafica_actual.py`

### Grupo 6 - duplicado exacto

- `src/60_orquestar_flujo_operativo_fondo3(1).py`
- `src/60_orquestar_flujo_operativo_fondo3.py`

### Grupo 7 - duplicado exacto

- `src/59_generar_panel_operativo_fondo3(1).py`
- `src/59_generar_panel_operativo_fondo3.py`

### Grupo 8 - duplicado exacto

- `src/58_archivar_y_validar_estimaciones_sbs(1).py`
- `src/58_archivar_y_validar_estimaciones_sbs.py`

### Grupo 9 - duplicado exacto

- `src/105_simulador_periodo_y_velas_fondo3.py`
- `src/97_simulador_monto_fondo3.py`

### Grupo 10 - duplicado exacto

- `data/processed/ca0001_modelo58_nuevas_validaciones.csv`
- `data/processed/ca0001_modelo58_validaciones_confirmadas.csv`

### Grupo 11 - duplicado exacto

- `data/processed/ca0001_modelo56_base_alineada.csv`
- `data/processed/ca0001_modelo56_base_alineada_BACKUP_20260705_124049.csv`

### Grupo 12 - duplicado exacto

- `80_monitor_sbs_y_validar_pronosticos_TABLERO_COMPLETO.py`
- `src/80_monitor_sbs_y_validar_pronosticos.py`

### Grupo 13 - duplicado exacto

- `data/processed/ca0001_modelo63_corregido_predicciones_diarias.csv`
- `data/processed/ca0001_modelo63_predicciones_baselines.csv`

### Grupo 14 - duplicado exacto

- `data/processed/ca0001_modelo80_metricas_prospectivas.csv`
- `data/processed/ca0001_modelo80_metricas_prospectivas_REVISAR_20260705_124811.csv`

### Grupo 15 - duplicado exacto

- `data/processed/ca0001_modelo79_auditoria_descargas.csv`
- `data/processed/ca0001_modelo79c_auditoria_descargas.csv`

### Grupo 16 - duplicado exacto

- `data/processed/ca0001_modelo72_screening_train_bvl.csv`
- `data/processed/ca0001_modelo72_top20_bvl_por_afp.csv`

## Temporales o de prueba

Candidatos claros: `src/__pycache__`, `*.pyc`, `notebooks/.ipynb_checkpoints`, `*.bak`, archivos con `BACKUP`, `RESPALDO`, `(1)`, `prueba`, `test`, `errores`, `logs_modelo60`.

## No tocar

No tocar sin respaldo y verificacion: `data/raw/**`, bases historicas, bases canonicas/maestras, vintages SBS, modelos `.joblib` y salidas finales que soportan reproducibilidad.

## Clasificacion exhaustiva por archivo

| Archivo | Clasificacion | Duplicado | Motivo | Tamano bytes | Modificado |
|---|---|---|---|---:|---|
| `100_instalar_cuota_sintetica_intradia.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 43588 | 2026-07-05 15:36:03 |
| `101_corregir_espera_sesion_intradia.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 44044 | 2026-07-05 15:39:38 |
| `103_instalar_tendencia_historica_y_acceso_celular.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 22268 | 2026-07-05 15:49:30 |
| `106_instalar_simulador_periodo_y_velas_fondo3.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 40929 | 2026-07-05 16:06:50 |
| `108_corregir_velas_del_simulador.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 39152 | 2026-07-05 16:35:12 |
| `110_corregir_escala_velas_y_aportes.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 68696 | 2026-07-05 16:47:23 |
| `112_instalar_vela_pronostico_historico.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 26523 | 2026-07-05 17:06:37 |
| `113_monitor_final_velas_diarias.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 34856 | 2026-07-05 20:41:48 |
| `114_instalar_monitor_final_velas_diarias.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 38714 | 2026-07-05 20:31:20 |
| `115_monitor_simple_fondo3.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 39325 | 2026-07-05 21:06:50 |
| `116_monitor_practico_fondo3.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 44401 | 2026-07-05 21:15:44 |
| `117_monitor_practico_fondo3.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 49709 | 2026-07-05 21:25:29 |
| `118_monitor_practico_fondo3.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 52447 | 2026-07-05 21:31:31 |
| `119_monitor_practico_fondo3.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 55713 | 2026-07-05 21:39:52 |
| `120_monitor_practico_fondo3_HISTORICO_COMPLETO.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 61785 | 2026-07-05 21:46:16 |
| `121_monitor_practico_fondo3_SIN_PROYECCION_INVENTADA.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 64099 | 2026-07-05 21:52:57 |
| `122_monitor_practico_fondo3_INTEGRADO_FINAL.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 69798 | 2026-07-05 22:02:20 |
| `123_monitor_practico_fondo3_EXPLICACION_MODELO.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 75888 | 2026-07-05 22:19:04 |
| `124_monitor_practico_fondo3_PRONOSTICO_VISIBLE.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 79315 | 2026-07-05 22:27:52 |
| `126_monitor_practico_fondo3_REAL_VS_MODELO_HISTORICO_FINAL.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 92344 | 2026-07-05 22:35:54 |
| `127_monitor_practico_fondo3_PRONOSTICO_DIA_A_DIA.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 95026 | 2026-07-05 22:45:27 |
| `128_monitor_practico_fondo3_SIMULADOR_DIA_A_DIA.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 95732 | 2026-07-05 22:53:35 |
| `129_monitor_fondo3_ACTUALIZA_Y_ABRE.py` | Mantener |  | Script raiz mas reciente para actualizar y abrir monitor. | 95740 | 2026-07-05 23:01:59 |
| `80_monitor_sbs_y_validar_pronosticos_TABLERO_COMPLETO.py` | Mover a archivo | Grupo 12 | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 35416 | 2026-07-05 13:15:30 |
| `80R_restaurar_base_antes_de_monitor.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 1774 | 2026-07-05 12:46:27 |
| `81_instalar_monitor_automatico_windows.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 4311 | 2026-07-05 12:53:26 |
| `83_instalar_monitor_afp_amigable.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 35419 | 2026-07-05 13:28:46 |
| `85_instalar_monitor_afp_interactivo.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 33671 | 2026-07-05 13:36:42 |
| `87_instalar_panel_indicadores_afp_intradia.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 35472 | 2026-07-05 13:47:29 |
| `91_corregir_monitor_solo_estimaciones_validas.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 40715 | 2026-07-05 14:13:57 |
| `93_instalar_panel_indicadores_didactico.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 27575 | 2026-07-05 14:20:35 |
| `94_ocultar_ventanas_automaticas_afp.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 5100 | 2026-07-05 14:25:56 |
| `95_corregir_navegacion_y_velas_indicadores.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 59642 | 2026-07-05 14:32:54 |
| `96_corregir_velas_japonesas_reales.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 10862 | 2026-07-05 14:36:56 |
| `98_instalar_simulador_monto_fondo3.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 17041 | 2026-07-05 15:57:53 |
| `ABRIR MONITOR EN CELULAR.bat` | Mover a archivo |  | Lanzador alternativo o legado. | 226 | 2026-07-05 15:49:49 |
| `ABRIR_MONITOR_PRACTICO_FONDO3.bat` | Mantener |  | Lanzador manual util para operacion local. | 176 | 2026-07-05 21:17:31 |
| `ABRIR_MONITOR_PRACTICO_FONDO3_V117.bat` | Mover a archivo |  | Acceso directo versionado/antiguo; dejar fuera del flujo principal. | 176 | 2026-07-05 21:26:05 |
| `ABRIR_MONITOR_PRACTICO_FONDO3_V118.bat` | Mover a archivo |  | Acceso directo versionado/antiguo; dejar fuera del flujo principal. | 176 | 2026-07-05 21:32:03 |
| `ABRIR_MONITOR_PRACTICO_FONDO3_V119.bat` | Mover a archivo |  | Acceso directo versionado/antiguo; dejar fuera del flujo principal. | 176 | 2026-07-05 21:40:33 |
| `ABRIR_MONITOR_PRACTICO_FONDO3_V120.bat` | Mover a archivo |  | Acceso directo versionado/antiguo; dejar fuera del flujo principal. | 195 | 2026-07-05 21:46:59 |
| `ABRIR_MONITOR_PRACTICO_FONDO3_V121.bat` | Mover a archivo |  | Acceso directo versionado/antiguo; dejar fuera del flujo principal. | 201 | 2026-07-05 21:53:38 |
| `ABRIR_MONITOR_PRACTICO_FONDO3_V122.bat` | Mover a archivo |  | Acceso directo versionado/antiguo; dejar fuera del flujo principal. | 192 | 2026-07-05 22:03:05 |
| `ABRIR_MONITOR_PRACTICO_FONDO3_V123.bat` | Mover a archivo |  | Acceso directo versionado/antiguo; dejar fuera del flujo principal. | 195 | 2026-07-05 22:20:19 |
| `ABRIR_MONITOR_PRACTICO_FONDO3_V124.bat` | Mover a archivo |  | Acceso directo versionado/antiguo; dejar fuera del flujo principal. | 195 | 2026-07-05 22:28:27 |
| `ABRIR_MONITOR_PRACTICO_FONDO3_V126.bat` | Mover a archivo |  | Acceso directo versionado/antiguo; dejar fuera del flujo principal. | 207 | 2026-07-05 22:36:30 |
| `ABRIR_MONITOR_PRACTICO_FONDO3_V127.bat` | Mover a archivo |  | Acceso directo versionado/antiguo; dejar fuera del flujo principal. | 197 | 2026-07-05 22:46:07 |
| `ABRIR_MONITOR_PRACTICO_FONDO3_V128.bat` | Mover a archivo |  | Acceso directo versionado/antiguo; dejar fuera del flujo principal. | 196 | 2026-07-05 22:54:09 |
| `ABRIR_MONITOR_SIMPLE_FONDO3.bat` | Mantener |  | Lanzador manual util para operacion local. | 174 | 2026-07-05 21:07:29 |
| `ACTUALIZAR MONITOR AFP.bat` | Mover a archivo |  | Lanzador alternativo o legado. | 287 | 2026-07-05 14:14:25 |
| `ACTUALIZAR Y ABRIR MONITOR AFP FINAL.bat` | Mover a archivo |  | Acceso directo versionado/antiguo; dejar fuera del flujo principal. | 356 | 2026-07-05 20:32:39 |
| `ACTUALIZAR Y ABRIR MONITOR AFP.bat` | Mover a archivo |  | Lanzador alternativo o legado. | 270 | 2026-07-05 13:29:06 |
| `ACTUALIZAR_Y_ABRIR_MONITOR_FONDO3.bat` | Mantener |  | Lanzador manual util para operacion local. | 197 | 2026-07-06 09:36:57 |
| `automatizacion/actualizar_cuota_sintetica_intradia.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 260 | 2026-07-05 15:36:25 |
| `automatizacion/actualizar_cuota_sintetica_intradia_oculto.vbs` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 238 | 2026-07-05 15:36:25 |
| `automatizacion/actualizar_indicadores_afp_intradia.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 262 | 2026-07-05 13:47:53 |
| `automatizacion/actualizar_indicadores_didacticos.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 262 | 2026-07-05 14:21:09 |
| `automatizacion/actualizar_intradia_y_simulador.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 329 | 2026-07-05 16:07:17 |
| `automatizacion/actualizar_intradia_y_simulador_oculto.vbs` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 234 | 2026-07-05 16:07:17 |
| `automatizacion/actualizar_monitor_final_5min.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 324 | 2026-07-05 20:32:39 |
| `automatizacion/actualizar_monitor_final_5min_oculto.vbs` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 232 | 2026-07-05 20:32:39 |
| `automatizacion/actualizar_sbs_y_monitor_final.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 333 | 2026-07-05 20:32:39 |
| `automatizacion/actualizar_sbs_y_monitor_final_oculto.vbs` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 233 | 2026-07-05 20:32:39 |
| `automatizacion/actualizar_vela_pronostico_historico.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 332 | 2026-07-05 17:07:42 |
| `automatizacion/actualizar_vela_pronostico_historico_oculto.vbs` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 239 | 2026-07-05 17:07:42 |
| `automatizacion/comprobar_sbs_cada_hora.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 319 | 2026-07-05 12:53:47 |
| `automatizacion/generar_pronostico_diario.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 339 | 2026-07-05 12:53:47 |
| `automatizacion/monitor_afp_amigable_diario.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 262 | 2026-07-05 13:29:06 |
| `automatizacion/monitor_afp_amigable_horario.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 249 | 2026-07-05 13:29:06 |
| `automatizacion/monitor_afp_interactivo_diario.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 265 | 2026-07-05 13:37:26 |
| `automatizacion/monitor_afp_interactivo_horario.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 252 | 2026-07-05 13:37:26 |
| `automatizacion/monitor_afp_solo_validos_diario.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 279 | 2026-07-05 14:14:25 |
| `automatizacion/monitor_afp_solo_validos_horario.bat` | Mantener |  | Automatizacion operativa para actualizar/abrir monitores. | 266 | 2026-07-05 14:14:25 |
| `automatizacion/oculto/afp_fondo3_indicadores_didacticos_oculto.vbs` | Mantener |  | Wrapper oculto para automatizaciones Windows activas. | 236 | 2026-07-05 14:26:17 |
| `automatizacion/oculto/afp_fondo3_monitor_sbs_oculto.vbs` | Mantener |  | Wrapper oculto para automatizaciones Windows activas. | 235 | 2026-07-05 14:30:00 |
| `automatizacion/oculto/afp_fondo3_pronostico_diario_oculto.vbs` | Mantener |  | Wrapper oculto para automatizaciones Windows activas. | 234 | 2026-07-05 14:30:03 |
| `data/processed/actualizaciones_modelo61/20260704_223131/fuentes/sbs_fondo3_extraido.csv` | Mover a archivo |  | Paquete de actualizacion con timestamp; conservar como evidencia historica. | 1404 | 2026-07-04 22:31:32 |
| `data/processed/actualizaciones_modelo61/20260704_223131/fuentes/sbs_variables_spp.html` | Mover a archivo |  | Paquete de actualizacion con timestamp; conservar como evidencia historica. | 98746 | 2026-07-04 22:31:32 |
| `data/processed/actualizaciones_modelo61/20260704_223131/fuentes/yfinance_descarga.csv` | Mover a archivo |  | Paquete de actualizacion con timestamp; conservar como evidencia historica. | 4015 | 2026-07-04 22:31:34 |
| `data/processed/ca0001_archivos_inspeccionados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1044 | 2026-07-04 17:38:40 |
| `data/processed/ca0001_auditoria_clusters_vectores_duplicados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 259321 | 2026-07-04 18:08:22 |
| `data/processed/ca0001_auditoria_filas_hoja10.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 6660621 | 2026-07-04 18:08:23 |
| `data/processed/ca0001_auditoria_filas_hoja3.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 7526540 | 2026-07-04 18:08:22 |
| `data/processed/ca0001_auditoria_ranking_hoja10.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2347 | 2026-07-04 18:08:23 |
| `data/processed/ca0001_auditoria_reconciliacion_hoja10.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1406071 | 2026-07-04 18:08:23 |
| `data/processed/ca0001_auditoria_reconciliacion_hoja3.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 175150 | 2026-07-04 18:08:23 |
| `data/processed/ca0001_auditoria_resumen_duplicados.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 210 | 2026-07-04 18:08:23 |
| `data/processed/ca0001_auditoria_resumen_reconciliacion_hoja3.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 348 | 2026-07-04 18:08:23 |
| `data/processed/ca0001_base_identificadores_canonica_final.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 14711691 | 2026-07-04 18:37:50 |
| `data/processed/ca0001_base_identificadores_colisiones.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 96 | 2026-07-04 18:37:50 |
| `data/processed/ca0001_base_identificadores_con_taxonomia.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 22739883 | 2026-07-04 18:41:23 |
| `data/processed/ca0001_base_identificadores_control_pesos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 60122 | 2026-07-04 18:37:50 |
| `data/processed/ca0001_base_identificadores_taxonomia_refinada.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 20738461 | 2026-07-04 18:44:31 |
| `data/processed/ca0001_cambios_estructura_historica.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 74019 | 2026-07-04 18:04:26 |
| `data/processed/ca0001_candidatos_encabezado.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 48813 | 2026-07-04 17:40:16 |
| `data/processed/ca0001_coincidencias_estructura.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 43248 | 2026-07-04 17:38:40 |
| `data/processed/ca0001_contextos_hojas_relevantes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 54921 | 2026-07-04 17:40:16 |
| `data/processed/ca0001_errores_inspeccion.csv` | Posible eliminar | Grupo 1 | Duplicado exacto de salida generada; validar antes de borrar si se usa como evidencia. | 5 | 2026-07-04 17:38:40 |
| `data/processed/ca0001_features_proxy_mercado_mensual_ancho.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 276501 | 2026-07-04 18:41:23 |
| `data/processed/ca0001_features_proxy_mercado_mensual_largo.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1310362 | 2026-07-04 18:41:23 |
| `data/processed/ca0001_features_proxy_refinado_mensual_ancho.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 276236 | 2026-07-04 18:44:31 |
| `data/processed/ca0001_features_proxy_refinado_mensual_largo.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1306713 | 2026-07-04 18:44:31 |
| `data/processed/ca0001_features_region_mensual.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1020688 | 2026-07-04 18:41:23 |
| `data/processed/ca0001_features_sector_tema_mensual.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 828617 | 2026-07-04 18:41:23 |
| `data/processed/ca0001_features_tipo_activo_mensual.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 388092 | 2026-07-04 18:41:23 |
| `data/processed/ca0001_fondo3_alertas_estabilidad_identificadores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 12185 | 2026-07-04 18:21:01 |
| `data/processed/ca0001_fondo3_control_columnas_hojas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 433 | 2026-07-04 17:48:33 |
| `data/processed/ca0001_fondo3_control_suma_pesos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 373763 | 2026-07-04 18:21:01 |
| `data/processed/ca0001_fondo3_features_mensuales_identificadores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 322659 | 2026-07-04 18:21:01 |
| `data/processed/ca0001_fondo3_historico_catalogo_emisores.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 229467 | 2026-07-04 18:00:23 |
| `data/processed/ca0001_fondo3_historico_catalogo_isin.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 271160 | 2026-07-04 18:00:23 |
| `data/processed/ca0001_fondo3_historico_control_archivos.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 27692 | 2026-07-04 18:00:23 |
| `data/processed/ca0001_fondo3_historico_control_grupos_hoja10.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 2499579 | 2026-07-04 18:00:23 |
| `data/processed/ca0001_fondo3_historico_control_hojas.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 60053 | 2026-07-04 18:00:23 |
| `data/processed/ca0001_fondo3_historico_errores.csv` | No tocar | Grupo 1 | Base historica/procesada clave para trazabilidad y backtesting. | 5 | 2026-07-04 18:00:23 |
| `data/processed/ca0001_fondo3_historico_fusiones.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 2378667 | 2026-07-04 18:00:23 |
| `data/processed/ca0001_fondo3_historico_hoja10_refinada.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 9312038 | 2026-07-04 18:00:23 |
| `data/processed/ca0001_fondo3_historico_hoja3_refinada.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 13070377 | 2026-07-04 18:00:22 |
| `data/processed/ca0001_fondo3_historico_hoja9_unidades.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 750810 | 2026-07-04 18:00:23 |
| `data/processed/ca0001_fondo3_historico_top_ultimo_mes.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 51770 | 2026-07-04 18:00:23 |
| `data/processed/ca0001_fondo3_hoja10_base_analisis_ampliado.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 16059648 | 2026-07-04 18:17:29 |
| `data/processed/ca0001_fondo3_hoja10_base_canonica_reconciliada.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 17404900 | 2026-07-04 18:17:28 |
| `data/processed/ca0001_fondo3_hoja10_base_modelo_principal.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 10368133 | 2026-07-04 18:17:28 |
| `data/processed/ca0001_fondo3_hoja10_catalogo_identificadores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 278767 | 2026-07-04 18:17:29 |
| `data/processed/ca0001_fondo3_hoja10_control_cobertura.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 117881 | 2026-07-04 18:17:29 |
| `data/processed/ca0001_fondo3_hoja10_control_grupos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 16826 | 2026-07-04 17:48:33 |
| `data/processed/ca0001_fondo3_hoja10_entidades_control_no_sumables.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2405162 | 2026-07-04 18:17:29 |
| `data/processed/ca0001_fondo3_hoja10_isin_canonicos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 64690 | 2026-07-04 17:48:33 |
| `data/processed/ca0001_fondo3_hoja10_refinada.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 72749 | 2026-07-04 17:51:24 |
| `data/processed/ca0001_fondo3_hoja10_resumen_estados_cobertura.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1681 | 2026-07-04 18:17:29 |
| `data/processed/ca0001_fondo3_hoja10_resumen_final.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 338 | 2026-07-04 18:17:29 |
| `data/processed/ca0001_fondo3_hoja10_top_ultimo_mes_reconciliado.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 42742 | 2026-07-04 18:17:29 |
| `data/processed/ca0001_fondo3_hoja3_emisores_canonicos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 76040 | 2026-07-04 17:48:33 |
| `data/processed/ca0001_fondo3_hoja3_incidencias.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2442 | 2026-07-04 17:48:33 |
| `data/processed/ca0001_fondo3_hoja3_refinada.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 93174 | 2026-07-04 17:51:24 |
| `data/processed/ca0001_fondo3_hoja9_fondos_locales_unidades.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5071 | 2026-07-04 17:48:33 |
| `data/processed/ca0001_fondo3_persistencia_identificadores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 672612 | 2026-07-04 18:21:01 |
| `data/processed/ca0001_fondo3_refinamiento_fusiones.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 12022 | 2026-07-04 17:51:24 |
| `data/processed/ca0001_fondo3_refinamiento_pendientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 26424 | 2026-07-04 17:51:24 |
| `data/processed/ca0001_fondo3_refinamiento_resumen.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 187 | 2026-07-04 17:51:24 |
| `data/processed/ca0001_fondo3_resumen_cobertura_features.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1215 | 2026-07-04 18:21:01 |
| `data/processed/ca0001_fondo3_resumen_depuracion.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 169 | 2026-07-04 17:48:33 |
| `data/processed/ca0001_fondo3_resumen_turnover.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 883 | 2026-07-04 18:21:01 |
| `data/processed/ca0001_fondo3_secuencias_elegibles.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1795 | 2026-07-04 18:21:01 |
| `data/processed/ca0001_fondo3_top_exposiciones_identificadas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 37743 | 2026-07-04 17:48:33 |
| `data/processed/ca0001_fondo3_top_refinado.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 54349 | 2026-07-04 17:51:24 |
| `data/processed/ca0001_fondo3_turnover_identificadores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 71803 | 2026-07-04 18:21:01 |
| `data/processed/ca0001_fp1356_candidatos_hoja10.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1264670 | 2026-07-04 18:04:26 |
| `data/processed/ca0001_fp1356_periodos_elegibles.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1453 | 2026-07-04 18:04:26 |
| `data/processed/ca0001_fp1356_periodos_excluidos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 46367 | 2026-07-04 18:04:26 |
| `data/processed/ca0001_fp1356_ranking_objetivos_hoja10.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 840 | 2026-07-04 18:04:26 |
| `data/processed/ca0001_fp1356_ranking_objetivos_hoja10_por_afp.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 1886 | 2026-07-04 18:04:26 |
| `data/processed/ca0001_fp1356_reconciliacion_hoja10.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 328544 | 2026-07-04 18:04:26 |
| `data/processed/ca0001_fp1356_reconciliacion_hoja3.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 129430 | 2026-07-04 18:04:26 |
| `data/processed/ca0001_fp1356_resumen_reconciliacion.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 379 | 2026-07-04 18:04:26 |
| `data/processed/ca0001_hoja10_auditoria_capas_detalle.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4940152 | 2026-07-04 18:15:12 |
| `data/processed/ca0001_hoja10_auditoria_capas_ranking.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 9262 | 2026-07-04 18:15:12 |
| `data/processed/ca0001_hoja10_auditoria_capas_ranking_por_afp.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 22761 | 2026-07-04 18:15:12 |
| `data/processed/ca0001_hoja10_auditoria_jerarquia_filas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 6491266 | 2026-07-04 18:12:00 |
| `data/processed/ca0001_hoja10_auditoria_relaciones_padre_hijos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 200639 | 2026-07-04 18:12:00 |
| `data/processed/ca0001_hoja10_contribucion_por_capa.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 493 | 2026-07-04 18:15:12 |
| `data/processed/ca0001_hoja10_control_jerarquia_por_periodo.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5684 | 2026-07-04 18:12:00 |
| `data/processed/ca0001_hoja10_deduplicada_auditoria.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 9391988 | 2026-07-04 18:08:23 |
| `data/processed/ca0001_hoja10_duplicados_identificador_valor.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 22310 | 2026-07-04 18:15:12 |
| `data/processed/ca0001_hoja10_hojas_jerarquia_auditoria.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 9643511 | 2026-07-04 18:12:00 |
| `data/processed/ca0001_hoja10_mejor_escenario_total_exterior.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1660 | 2026-07-04 18:15:12 |
| `data/processed/ca0001_hoja10_ranking_jerarquia.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2395 | 2026-07-04 18:12:00 |
| `data/processed/ca0001_hoja10_reconciliacion_jerarquia.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1425360 | 2026-07-04 18:12:00 |
| `data/processed/ca0001_hoja10_resumen_duplicados_identificador.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 190 | 2026-07-04 18:15:12 |
| `data/processed/ca0001_hoja10_resumen_jerarquia.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 168 | 2026-07-04 18:12:00 |
| `data/processed/ca0001_hoja3_deduplicada_auditoria.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 13220346 | 2026-07-04 18:08:23 |
| `data/processed/ca0001_identificadores_correcciones_aprobadas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4668 | 2026-07-04 18:37:49 |
| `data/processed/ca0001_identificadores_correcciones_pendientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 858 | 2026-07-04 18:37:49 |
| `data/processed/ca0001_identificadores_decisiones_checksum.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5060 | 2026-07-04 18:37:49 |
| `data/processed/ca0001_identificadores_pendientes_finales.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 27005 | 2026-07-04 18:37:50 |
| `data/processed/ca0001_identificadores_resumen_final.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 667 | 2026-07-04 18:37:50 |
| `data/processed/ca0001_inventario_enlaces.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 14785 | 2026-07-04 17:38:36 |
| `data/processed/ca0001_inventario_hojas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3960 | 2026-07-04 17:38:40 |
| `data/processed/ca0001_isin_correcciones_checksum_propuestas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3651 | 2026-07-04 18:32:45 |
| `data/processed/ca0001_isin_openfigi_ambiguedad_clasificada.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 32908 | 2026-07-04 18:32:45 |
| `data/processed/ca0001_isin_openfigi_ambiguos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 97139 | 2026-07-04 18:29:55 |
| `data/processed/ca0001_isin_openfigi_control.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 429 | 2026-07-04 18:29:55 |
| `data/processed/ca0001_isin_openfigi_mapeo_canonico.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 194166 | 2026-07-04 18:32:45 |
| `data/processed/ca0001_isin_openfigi_mapeo_seleccionado.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 234662 | 2026-07-04 18:29:55 |
| `data/processed/ca0001_isin_openfigi_no_resueltos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 30403 | 2026-07-04 18:29:55 |
| `data/processed/ca0001_isin_openfigi_resumen_ambiguedad.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 184 | 2026-07-04 18:32:45 |
| `data/processed/ca0001_isin_openfigi_todos_resultados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2649269 | 2026-07-04 18:29:55 |
| `data/processed/ca0001_isin_revision_manual_priorizada.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 25978 | 2026-07-04 18:32:45 |
| `data/processed/ca0001_isin_universo_priorizado.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 148951 | 2026-07-04 18:29:55 |
| `data/processed/ca0001_maestro_identificadores_canonico_final.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 279014 | 2026-07-04 18:37:49 |
| `data/processed/ca0001_modelo102_tendencia_y_velas_cuota.html` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 518068 | 2026-07-05 15:49:50 |
| `data/processed/ca0001_modelo111_vela_pronostico_historico.html` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 101085 | 2026-07-05 22:55:26 |
| `data/processed/ca0001_modelo41_archivos_detectados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 581 | 2026-07-04 19:02:31 |
| `data/processed/ca0001_modelo41_bootstrap_placebos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 19749 | 2026-07-04 19:02:31 |
| `data/processed/ca0001_modelo41_cobertura_temporal.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1796 | 2026-07-04 19:02:31 |
| `data/processed/ca0001_modelo41_control_factores_mercado.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1005 | 2026-07-04 19:02:31 |
| `data/processed/ca0001_modelo41_control_fecha_cuotas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 197 | 2026-07-04 19:02:31 |
| `data/processed/ca0001_modelo41_control_integridad_cuotas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 530 | 2026-07-04 19:02:31 |
| `data/processed/ca0001_modelo41_predicciones_oos.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 19330619 | 2026-07-04 19:02:31 |
| `data/processed/ca0001_modelo41_ranking_variantes.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 10729 | 2026-07-04 19:02:31 |
| `data/processed/ca0001_modelo41_resultados_oos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 25366 | 2026-07-04 19:02:31 |
| `data/processed/ca0001_modelo42_estabilidad_anual.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 51880 | 2026-07-04 19:10:40 |
| `data/processed/ca0001_modelo42_perdidas_emparejadas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5918799 | 2026-07-04 19:10:40 |
| `data/processed/ca0001_modelo42_ranking_uniforme.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 1149 | 2026-07-04 19:10:40 |
| `data/processed/ca0001_modelo42_resumen_robustez.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 21548 | 2026-07-04 19:10:40 |
| `data/processed/ca0001_modelo42_rolling_252.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3574918 | 2026-07-04 19:10:40 |
| `data/processed/ca0001_modelo42_seleccion_uniforme.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 405 | 2026-07-04 19:10:40 |
| `data/processed/ca0001_modelo42_seleccion_uniforme_por_afp.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4610 | 2026-07-04 19:10:40 |
| `data/processed/ca0001_modelo43_configuracion_final.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 520 | 2026-07-04 19:13:29 |
| `data/processed/ca0001_modelo43_control.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 232 | 2026-07-04 19:13:29 |
| `data/processed/ca0001_modelo43_politica_operativa.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 946 | 2026-07-04 19:13:29 |
| `data/processed/ca0001_modelo43_predicciones_blend_dinamico.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 951167 | 2026-07-04 19:13:29 |
| `data/processed/ca0001_modelo43_pruebas_blend.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 1594 | 2026-07-04 19:13:29 |
| `data/processed/ca0001_modelo43_resumen_blend.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 2092 | 2026-07-04 19:13:29 |
| `data/processed/ca0001_modelo43_trayectoria_lambda.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 25383 | 2026-07-04 19:13:29 |
| `data/processed/ca0001_modelo44_configuracion_produccion.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 2959 | 2026-07-04 19:16:30 |
| `data/processed/ca0001_modelo44_configuracion_produccion.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 7085 | 2026-07-04 19:16:30 |
| `data/processed/ca0001_modelo44_control.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 324 | 2026-07-04 19:16:30 |
| `data/processed/ca0001_modelo44_estado_operativo.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 951 | 2026-07-04 19:16:30 |
| `data/processed/ca0001_modelo45_candidatos_prediccion.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1625 | 2026-07-04 19:24:21 |
| `data/processed/ca0001_modelo45_control.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 567 | 2026-07-04 19:24:21 |
| `data/processed/ca0001_modelo45_nowcast_operativo.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1068 | 2026-07-04 19:24:21 |
| `data/processed/ca0001_modelo45_nowcast_operativo.json` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4181 | 2026-07-04 19:24:21 |
| `data/processed/ca0001_modelo46_auditoria_semantica_archivos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3170 | 2026-07-04 19:26:14 |
| `data/processed/ca0001_modelo46_filas_ultima_fecha.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3035 | 2026-07-04 19:26:14 |
| `data/processed/ca0001_modelo47_control.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 433 | 2026-07-04 19:28:28 |
| `data/processed/ca0001_modelo47_mapeo_estimadores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 373 | 2026-07-04 19:28:28 |
| `data/processed/ca0001_modelo47_nowcast_actual_validado.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1353 | 2026-07-04 19:28:28 |
| `data/processed/ca0001_modelo47_nowcast_actual_validado.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 5538 | 2026-07-04 19:28:28 |
| `data/processed/ca0001_modelo47_resumen_sistema.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 366 | 2026-07-04 19:28:28 |
| `data/processed/ca0001_modelo48_alertas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 276 | 2026-07-04 19:30:29 |
| `data/processed/ca0001_modelo48_reporte_operativo_diario.json` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 6360 | 2026-07-04 19:30:29 |
| `data/processed/ca0001_modelo48_reporte_operativo_diario.md` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1532 | 2026-07-04 19:30:29 |
| `data/processed/ca0001_modelo48_resumen_ejecutivo.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 669 | 2026-07-04 19:30:29 |
| `data/processed/ca0001_modelo48_tendencia_detalle.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1142 | 2026-07-04 19:30:29 |
| `data/processed/ca0001_modelo48_tendencia_resumen.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 501 | 2026-07-04 19:30:29 |
| `data/processed/ca0001_modelo49_control.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 426 | 2026-07-04 19:33:44 |
| `data/processed/ca0001_modelo49_metricas_por_afp.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 473 | 2026-07-04 19:33:44 |
| `data/processed/ca0001_modelo49_pendientes_publicacion.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1203 | 2026-07-04 19:33:44 |
| `data/processed/ca0001_modelo49_resumen_global.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 481 | 2026-07-04 19:33:44 |
| `data/processed/ca0001_modelo49_validacion_expost.json` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 7347 | 2026-07-04 19:33:44 |
| `data/processed/ca0001_modelo49_validacion_expost_detalle.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1722 | 2026-07-04 19:33:44 |
| `data/processed/ca0001_modelo50_control.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 438 | 2026-07-04 20:12:46 |
| `data/processed/ca0001_modelo50_correlaciones_rezagadas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 26594 | 2026-07-04 20:12:46 |
| `data/processed/ca0001_modelo50_division_temporal.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 346 | 2026-07-04 20:12:46 |
| `data/processed/ca0001_modelo50_metricas_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 1273 | 2026-07-04 20:12:46 |
| `data/processed/ca0001_modelo50_predicciones_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 149802 | 2026-07-04 20:12:46 |
| `data/processed/ca0001_modelo50_relaciones_seleccionadas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 7545 | 2026-07-04 20:12:46 |
| `data/processed/ca0001_modelo50_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 27953 | 2026-07-04 20:12:46 |
| `data/processed/ca0001_modelo50_transformacion_factores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1723 | 2026-07-04 20:12:46 |
| `data/processed/ca0001_modelo51_auditoria_descartes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3504 | 2026-07-04 20:19:59 |
| `data/processed/ca0001_modelo51_canasta_comun.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 643 | 2026-07-04 20:19:59 |
| `data/processed/ca0001_modelo51_canasta_depurada.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1516 | 2026-07-04 20:19:59 |
| `data/processed/ca0001_modelo51_metricas_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 895 | 2026-07-04 20:19:59 |
| `data/processed/ca0001_modelo51_predicciones_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 137047 | 2026-07-04 20:19:59 |
| `data/processed/ca0001_modelo51_reporte.md` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2153 | 2026-07-04 20:19:59 |
| `data/processed/ca0001_modelo51_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 8065 | 2026-07-04 20:19:59 |
| `data/processed/ca0001_modelo52_comparacion_cuota.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 491682 | 2026-07-04 20:22:41 |
| `data/processed/ca0001_modelo52_metricas.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 776 | 2026-07-04 20:22:41 |
| `data/processed/ca0001_modelo52_reporte.md` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1885 | 2026-07-04 20:22:41 |
| `data/processed/ca0001_modelo52_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 2664 | 2026-07-04 20:22:44 |
| `data/processed/ca0001_modelo53_metricas_por_lag.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 3603 | 2026-07-04 20:25:35 |
| `data/processed/ca0001_modelo53_reporte.md` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1583 | 2026-07-04 20:25:35 |
| `data/processed/ca0001_modelo53_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 5877 | 2026-07-04 20:25:37 |
| `data/processed/ca0001_modelo53_resumen_lag_4_5.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1791 | 2026-07-04 20:25:35 |
| `data/processed/ca0001_modelo53_simulacion_desfase.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 1896833 | 2026-07-04 20:25:35 |
| `data/processed/ca0001_modelo54_auditoria_continuidad.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 122905 | 2026-07-04 20:28:34 |
| `data/processed/ca0001_modelo54_metricas_calendario.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2838 | 2026-07-04 20:28:34 |
| `data/processed/ca0001_modelo54_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 10082 | 2026-07-04 20:28:34 |
| `data/processed/ca0001_modelo54_resumen_brechas.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 308 | 2026-07-04 20:28:34 |
| `data/processed/ca0001_modelo54_simulacion_calendario.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 757098 | 2026-07-04 20:28:34 |
| `data/processed/ca0001_modelo55_auditoria_fechas_prediccion.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 236776 | 2026-07-04 20:32:04 |
| `data/processed/ca0001_modelo55_brechas_prediccion.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2827 | 2026-07-04 20:32:04 |
| `data/processed/ca0001_modelo55_fechas_faltantes_comunes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 25168 | 2026-07-04 20:32:04 |
| `data/processed/ca0001_modelo55_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 66815 | 2026-07-04 20:32:04 |
| `data/processed/ca0001_modelo55_resumen_cobertura.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 390 | 2026-07-04 20:32:04 |
| `data/processed/ca0001_modelo55_transformaciones_factores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 932 | 2026-07-04 20:32:04 |
| `data/processed/ca0001_modelo56_auditoria_factores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 286 | 2026-07-04 20:38:29 |
| `data/processed/ca0001_modelo56_base_alineada.csv` | Mover a archivo | Grupo 11 | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2216323 | 2026-07-04 20:38:29 |
| `data/processed/ca0001_modelo56_base_alineada_BACKUP_20260705_124049.csv` | Mover a archivo | Grupo 11 | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 2216323 | 2026-07-04 20:38:29 |
| `data/processed/ca0001_modelo56_base_alineada_REVISAR_20260705_124811.csv` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 2136988 | 2026-07-05 12:40:49 |
| `data/processed/ca0001_modelo56_controles.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 544 | 2026-07-04 20:38:29 |
| `data/processed/ca0001_modelo56_metricas.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 953 | 2026-07-04 20:38:29 |
| `data/processed/ca0001_modelo56_modelos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1373 | 2026-07-04 20:38:29 |
| `data/processed/ca0001_modelo56_predicciones_diarias.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 180230 | 2026-07-04 20:38:29 |
| `data/processed/ca0001_modelo56_reporte.md` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2387 | 2026-07-04 20:38:29 |
| `data/processed/ca0001_modelo56_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 10140 | 2026-07-04 20:38:29 |
| `data/processed/ca0001_modelo56_simulacion_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 474597 | 2026-07-04 20:38:29 |
| `data/processed/ca0001_modelo56_ultima_ventana.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1107 | 2026-07-04 20:38:29 |
| `data/processed/ca0001_modelo57_contribuciones.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4556 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo57_controles.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 681 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo57_estimaciones_pendientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1807 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo57_reporte.md` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2433 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo57_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 5276 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo57_resumen_actual.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1263 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo58_archivo_pronosticos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3163 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo58_controles.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 509 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo58_metricas.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 595 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo58_nuevas_validaciones.csv` | Posible eliminar | Grupo 10 | Duplicado exacto de salida generada; validar antes de borrar si se usa como evidencia. | 538 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo58_pronosticos_pendientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4252 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo58_reconciliacion_contribuciones.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1344 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo58_reporte.md` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1409 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo58_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 5497 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo58_validacion_completa.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4019 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo58_validaciones_confirmadas.csv` | Posible eliminar | Grupo 10 | Duplicado exacto de salida generada; validar antes de borrar si se usa como evidencia. | 538 | 2026-07-04 22:51:13 |
| `data/processed/ca0001_modelo59_alertas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1615 | 2026-07-04 22:51:15 |
| `data/processed/ca0001_modelo59_contribuciones_resumen.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1099 | 2026-07-04 22:51:15 |
| `data/processed/ca0001_modelo59_panel_actual.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 2343 | 2026-07-04 22:51:15 |
| `data/processed/ca0001_modelo59_reporte.md` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5301 | 2026-07-04 22:51:15 |
| `data/processed/ca0001_modelo59_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 9662 | 2026-07-04 22:51:15 |
| `data/processed/ca0001_modelo59_resumen_validacion.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 344 | 2026-07-04 22:51:15 |
| `data/processed/ca0001_modelo60_estado_ultima_ejecucion.json` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 7351 | 2026-07-04 22:51:15 |
| `data/processed/ca0001_modelo60_resumen_ultima_ejecucion.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 2340 | 2026-07-04 22:51:15 |
| `data/processed/ca0001_modelo61_control_mercados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 488 | 2026-07-04 22:31:34 |
| `data/processed/ca0001_modelo61_controles.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 417 | 2026-07-04 22:31:34 |
| `data/processed/ca0001_modelo61_resumen_actualizacion.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 2160 | 2026-07-04 22:31:34 |
| `data/processed/ca0001_modelo62_correlacion_beta_moviles.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3075405 | 2026-07-04 23:04:20 |
| `data/processed/ca0001_modelo62_correlaciones_rezagadas_train.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2655 | 2026-07-04 23:04:20 |
| `data/processed/ca0001_modelo62_diagnostico_series_train.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1485 | 2026-07-04 23:04:20 |
| `data/processed/ca0001_modelo62_modelos_sugeridos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1630 | 2026-07-04 23:04:20 |
| `data/processed/ca0001_modelo62_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 2936 | 2026-07-04 23:04:20 |
| `data/processed/ca0001_modelo62_resumen_relaciones_train.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 2283 | 2026-07-04 23:04:20 |
| `data/processed/ca0001_modelo62_vif_train.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 673 | 2026-07-04 23:04:20 |
| `data/processed/ca0001_modelo63_corregido_metricas_diarias.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 9836 | 2026-07-04 23:23:58 |
| `data/processed/ca0001_modelo63_corregido_metricas_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 10268 | 2026-07-04 23:23:58 |
| `data/processed/ca0001_modelo63_corregido_predicciones_diarias.csv` | Mover a archivo | Grupo 13 | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 4490234 | 2026-07-04 23:23:58 |
| `data/processed/ca0001_modelo63_corregido_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 367 | 2026-07-04 23:23:58 |
| `data/processed/ca0001_modelo63_corregido_simulacion_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 8505822 | 2026-07-04 23:23:58 |
| `data/processed/ca0001_modelo63_metricas_diarias_baselines.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 9850 | 2026-07-04 23:20:00 |
| `data/processed/ca0001_modelo63_metricas_publicacion_5d_baselines.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 10268 | 2026-07-04 23:20:00 |
| `data/processed/ca0001_modelo63_predicciones_baselines.csv` | Posible eliminar | Grupo 13 | Duplicado exacto de salida generada; validar antes de borrar si se usa como evidencia. | 4490234 | 2026-07-04 23:20:00 |
| `data/processed/ca0001_modelo63_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 18718 | 2026-07-04 23:20:00 |
| `data/processed/ca0001_modelo63_resumen_prueba_baselines.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 6361 | 2026-07-04 23:20:00 |
| `data/processed/ca0001_modelo63_simulacion_publicacion_5d_baselines.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 8518054 | 2026-07-04 23:20:00 |
| `data/processed/ca0001_modelo64_diagnosticos_residuales.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 13105 | 2026-07-04 23:44:04 |
| `data/processed/ca0001_modelo64_diebold_mariano.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5924 | 2026-07-04 23:44:04 |
| `data/processed/ca0001_modelo64_metricas_diarias.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 19002 | 2026-07-04 23:44:04 |
| `data/processed/ca0001_modelo64_metricas_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 20357 | 2026-07-04 23:44:04 |
| `data/processed/ca0001_modelo64_predicciones_diarias.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 7710296 | 2026-07-04 23:44:04 |
| `data/processed/ca0001_modelo64_ranking_modelos.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 5154 | 2026-07-04 23:44:04 |
| `data/processed/ca0001_modelo64_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 16232 | 2026-07-04 23:44:04 |
| `data/processed/ca0001_modelo64_seleccion_hiperparametros.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 37864 | 2026-07-04 23:44:04 |
| `data/processed/ca0001_modelo64_simulacion_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 14959335 | 2026-07-04 23:44:04 |
| `data/processed/ca0001_modelo65_diagnosticos_residuales.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3264 | 2026-07-05 00:09:16 |
| `data/processed/ca0001_modelo65_diebold_mariano.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 683 | 2026-07-05 00:09:16 |
| `data/processed/ca0001_modelo65_diebold_mariano_CORREGIDO.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 908 | 2026-07-05 00:16:21 |
| `data/processed/ca0001_modelo65_metricas_diarias.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 7595 | 2026-07-05 00:09:15 |
| `data/processed/ca0001_modelo65_metricas_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 6977 | 2026-07-05 00:09:15 |
| `data/processed/ca0001_modelo65_predicciones_diarias.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2183802 | 2026-07-05 00:09:16 |
| `data/processed/ca0001_modelo65_ranking_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 3650 | 2026-07-05 00:09:16 |
| `data/processed/ca0001_modelo65_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 10246 | 2026-07-05 00:09:16 |
| `data/processed/ca0001_modelo65_seleccion_dinamicos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 21642 | 2026-07-05 00:09:15 |
| `data/processed/ca0001_modelo65_simulacion_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 3946207 | 2026-07-05 00:09:16 |
| `data/processed/ca0001_modelo65C_control_cruce_fechas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1130 | 2026-07-05 00:19:51 |
| `data/processed/ca0001_modelo65C_diebold_mariano_final.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1683 | 2026-07-05 00:19:51 |
| `data/processed/ca0001_modelo66_diebold_mariano_vs_ew.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4704 | 2026-07-05 00:54:36 |
| `data/processed/ca0001_modelo66_ganadores_validacion.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 282 | 2026-07-05 00:54:36 |
| `data/processed/ca0001_modelo66_importancia_variables.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5597 | 2026-07-05 00:54:36 |
| `data/processed/ca0001_modelo66_metricas_comparables.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 54320 | 2026-07-05 00:54:35 |
| `data/processed/ca0001_modelo66_ranking_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 19363 | 2026-07-05 00:54:36 |
| `data/processed/ca0001_modelo66_ranking_validacion.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 19185 | 2026-07-05 00:54:36 |
| `data/processed/ca0001_modelo66_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 972 | 2026-07-05 00:54:36 |
| `data/processed/ca0001_modelo66_seleccion_hiperparametros.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 81890 | 2026-07-05 00:54:35 |
| `data/processed/ca0001_modelo66_simulaciones_cuota.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 28773042 | 2026-07-05 00:54:36 |
| `data/processed/ca0001_modelo67_diebold_mariano_vs_ew.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 750 | 2026-07-05 01:00:58 |
| `data/processed/ca0001_modelo67_estabilidad_subperiodos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4753 | 2026-07-05 01:00:58 |
| `data/processed/ca0001_modelo67_grid_ensembles_validacion.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 254952 | 2026-07-05 01:00:58 |
| `data/processed/ca0001_modelo67_metricas_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 1501 | 2026-07-05 01:00:58 |
| `data/processed/ca0001_modelo67_pesos_seleccionados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 740 | 2026-07-05 01:00:58 |
| `data/processed/ca0001_modelo67_predicciones_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 816276 | 2026-07-05 01:00:58 |
| `data/processed/ca0001_modelo67_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 4550 | 2026-07-05 01:00:58 |
| `data/processed/ca0001_modelo68_calibracion_seleccionada.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 573 | 2026-07-05 01:07:17 |
| `data/processed/ca0001_modelo68_diebold_mariano.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 474 | 2026-07-05 01:07:17 |
| `data/processed/ca0001_modelo68_estabilidad_subperiodos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 6066 | 2026-07-05 01:07:17 |
| `data/processed/ca0001_modelo68_metricas_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 1874 | 2026-07-05 01:07:17 |
| `data/processed/ca0001_modelo68_metricas_validacion.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 19177 | 2026-07-05 01:07:17 |
| `data/processed/ca0001_modelo68_predicciones_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 486808 | 2026-07-05 01:07:17 |
| `data/processed/ca0001_modelo68_pruebas_cambio_regimen.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 430 | 2026-07-05 01:07:17 |
| `data/processed/ca0001_modelo68_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 5817 | 2026-07-05 01:07:17 |
| `data/processed/ca0001_modelo69_auditoria_descarga.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 6349 | 2026-07-05 01:30:58 |
| `data/processed/ca0001_modelo69_auditoria_factores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 25610 | 2026-07-05 01:30:58 |
| `data/processed/ca0001_modelo69_catalogo_factores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 12362 | 2026-07-05 01:30:58 |
| `data/processed/ca0001_modelo69_factores_ampliados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 9135183 | 2026-07-05 01:30:58 |
| `data/processed/ca0001_modelo69_factores_casi_duplicados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 438 | 2026-07-05 01:30:58 |
| `data/processed/ca0001_modelo69_precios_ampliados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4205073 | 2026-07-05 01:30:58 |
| `data/processed/ca0001_modelo69_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 451 | 2026-07-05 01:30:58 |
| `data/processed/ca0001_modelo69_screening_train.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 72275 | 2026-07-05 01:30:58 |
| `data/processed/ca0001_modelo69_top25_por_afp.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 12416 | 2026-07-05 01:30:58 |
| `data/processed/ca0001_modelo70_canasta_seleccionada.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3381 | 2026-07-05 02:26:25 |
| `data/processed/ca0001_modelo70_coeficientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2844 | 2026-07-05 02:26:25 |
| `data/processed/ca0001_modelo70_diebold_mariano.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 515 | 2026-07-05 02:26:25 |
| `data/processed/ca0001_modelo70_metricas_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2522 | 2026-07-05 02:26:25 |
| `data/processed/ca0001_modelo70_metricas_validacion.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2517 | 2026-07-05 02:26:25 |
| `data/processed/ca0001_modelo70_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 17597 | 2026-07-05 02:26:25 |
| `data/processed/ca0001_modelo70_simulacion_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 801202 | 2026-07-05 02:26:25 |
| `data/processed/ca0001_modelo70_trazabilidad_backward.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1000 | 2026-07-05 02:26:25 |
| `data/processed/ca0001_modelo70_trazabilidad_forward.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3012 | 2026-07-05 02:26:25 |
| `data/processed/ca0001_modelo71_acciones_seleccionadas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 773 | 2026-07-05 09:36:41 |
| `data/processed/ca0001_modelo71_coeficientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3944 | 2026-07-05 09:36:41 |
| `data/processed/ca0001_modelo71_diebold_mariano.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 562 | 2026-07-05 09:36:41 |
| `data/processed/ca0001_modelo71_metricas_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2621 | 2026-07-05 09:36:41 |
| `data/processed/ca0001_modelo71_metricas_validacion.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2624 | 2026-07-05 09:36:41 |
| `data/processed/ca0001_modelo71_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 9410 | 2026-07-05 09:36:41 |
| `data/processed/ca0001_modelo71_screening_acciones_train.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 22840 | 2026-07-05 09:36:41 |
| `data/processed/ca0001_modelo71_simulacion_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 829622 | 2026-07-05 09:36:41 |
| `data/processed/ca0001_modelo71_trazabilidad_seleccion.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2156 | 2026-07-05 09:36:41 |
| `data/processed/ca0001_modelo72_auditoria_alias_bvl.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5573 | 2026-07-05 09:52:15 |
| `data/processed/ca0001_modelo72_auditoria_factores_bvl.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4468 | 2026-07-05 09:52:15 |
| `data/processed/ca0001_modelo72_catalogo_factores_bvl.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2353 | 2026-07-05 09:52:15 |
| `data/processed/ca0001_modelo72_factores_bvl.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 951807 | 2026-07-05 09:52:15 |
| `data/processed/ca0001_modelo72_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 329 | 2026-07-05 09:52:15 |
| `data/processed/ca0001_modelo72_screening_train_bvl.csv` | Mover a archivo | Grupo 16 | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 16089 | 2026-07-05 09:52:15 |
| `data/processed/ca0001_modelo72_top20_bvl_por_afp.csv` | Posible eliminar | Grupo 16 | Duplicado exacto de salida generada; validar antes de borrar si se usa como evidencia. | 16089 | 2026-07-05 09:52:15 |
| `data/processed/ca0001_modelo73_coeficientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5147 | 2026-07-05 10:22:57 |
| `data/processed/ca0001_modelo73_diebold_mariano.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 561 | 2026-07-05 10:22:57 |
| `data/processed/ca0001_modelo73_estabilidad_subperiodos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 6179 | 2026-07-05 10:22:57 |
| `data/processed/ca0001_modelo73_factores_bvl_seleccionados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1262 | 2026-07-05 10:22:57 |
| `data/processed/ca0001_modelo73_metricas_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2623 | 2026-07-05 10:22:57 |
| `data/processed/ca0001_modelo73_metricas_validacion.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2626 | 2026-07-05 10:22:57 |
| `data/processed/ca0001_modelo73_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 11481 | 2026-07-05 10:22:57 |
| `data/processed/ca0001_modelo73_simulacion_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 832131 | 2026-07-05 10:22:57 |
| `data/processed/ca0001_modelo73_trazabilidad_seleccion.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3484 | 2026-07-05 10:22:57 |
| `data/processed/ca0001_modelo74_auditoria_descarga_indices.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2174 | 2026-07-05 10:26:31 |
| `data/processed/ca0001_modelo74_auditoria_factores_indices.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2898 | 2026-07-05 10:26:31 |
| `data/processed/ca0001_modelo74_catalogo_indices.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 6605 | 2026-07-05 10:26:31 |
| `data/processed/ca0001_modelo74_factores_indices.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3614151 | 2026-07-05 10:26:31 |
| `data/processed/ca0001_modelo74_indices_casi_duplicados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 218 | 2026-07-05 10:26:31 |
| `data/processed/ca0001_modelo74_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 390 | 2026-07-05 10:26:31 |
| `data/processed/ca0001_modelo74_screening_train_indices.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 50022 | 2026-07-05 10:26:31 |
| `data/processed/ca0001_modelo74_top20_por_afp.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 18011 | 2026-07-05 10:26:31 |
| `data/processed/ca0001_modelo75_canasta_con_indices.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2111 | 2026-07-05 10:52:14 |
| `data/processed/ca0001_modelo75_coeficientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 6212 | 2026-07-05 10:52:14 |
| `data/processed/ca0001_modelo75_diebold_mariano.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 538 | 2026-07-05 10:52:14 |
| `data/processed/ca0001_modelo75_estabilidad_subperiodos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 6310 | 2026-07-05 10:52:14 |
| `data/processed/ca0001_modelo75_metricas_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2662 | 2026-07-05 10:52:14 |
| `data/processed/ca0001_modelo75_metricas_validacion.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2660 | 2026-07-05 10:52:14 |
| `data/processed/ca0001_modelo75_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 17418 | 2026-07-05 10:52:14 |
| `data/processed/ca0001_modelo75_simulacion_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 851181 | 2026-07-05 10:52:14 |
| `data/processed/ca0001_modelo75_trazabilidad_adiciones.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1602 | 2026-07-05 10:52:14 |
| `data/processed/ca0001_modelo75_trazabilidad_sustituciones.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1114 | 2026-07-05 10:52:14 |
| `data/processed/ca0001_modelo76_auditoria_descarga.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2627 | 2026-07-05 10:53:49 |
| `data/processed/ca0001_modelo76_catalogo_futuros_cripto.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4401 | 2026-07-05 10:53:49 |
| `data/processed/ca0001_modelo76_factores_casi_duplicados.csv` | Mover a archivo | Grupo 1 | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5 | 2026-07-05 10:53:49 |
| `data/processed/ca0001_modelo76_factores_futuros_cripto.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2861650 | 2026-07-05 10:53:49 |
| `data/processed/ca0001_modelo76_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 392 | 2026-07-05 10:53:49 |
| `data/processed/ca0001_modelo76_screening_train.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 35674 | 2026-07-05 10:53:49 |
| `data/processed/ca0001_modelo76_top20_por_afp.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 16585 | 2026-07-05 10:53:49 |
| `data/processed/ca0001_modelo77_canasta_final.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 2214 | 2026-07-05 11:21:49 |
| `data/processed/ca0001_modelo77_coeficientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 6419 | 2026-07-05 11:21:49 |
| `data/processed/ca0001_modelo77_diebold_mariano.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 562 | 2026-07-05 11:21:49 |
| `data/processed/ca0001_modelo77_mejor_por_categoria.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5842 | 2026-07-05 11:21:49 |
| `data/processed/ca0001_modelo77_metricas_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2628 | 2026-07-05 11:21:49 |
| `data/processed/ca0001_modelo77_metricas_validacion.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2632 | 2026-07-05 11:21:49 |
| `data/processed/ca0001_modelo77_ranking_individual_validacion.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 18858 | 2026-07-05 11:21:49 |
| `data/processed/ca0001_modelo77_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 18022 | 2026-07-05 11:21:49 |
| `data/processed/ca0001_modelo77_simulacion_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 832266 | 2026-07-05 11:21:49 |
| `data/processed/ca0001_modelo77_trazabilidad_forward.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2287 | 2026-07-05 11:21:49 |
| `data/processed/ca0001_modelo78_canasta_con_evidencia.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 831 | 2026-07-05 11:31:37 |
| `data/processed/ca0001_modelo78_canasta_final_podada.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1512 | 2026-07-05 11:31:37 |
| `data/processed/ca0001_modelo78_coeficientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4301 | 2026-07-05 11:31:37 |
| `data/processed/ca0001_modelo78_diebold_mariano_poda.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 452 | 2026-07-05 11:31:37 |
| `data/processed/ca0001_modelo78_historial_modelos_aceptados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 158 | 2026-07-05 11:31:37 |
| `data/processed/ca0001_modelo78_metricas_prueba.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2246 | 2026-07-05 11:31:37 |
| `data/processed/ca0001_modelo78_metricas_validacion.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2251 | 2026-07-05 11:31:37 |
| `data/processed/ca0001_modelo78_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 13050 | 2026-07-05 11:31:37 |
| `data/processed/ca0001_modelo78_simulacion_publicacion_5d.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 834600 | 2026-07-05 11:31:37 |
| `data/processed/ca0001_modelo78_trazabilidad_poda.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1667 | 2026-07-05 11:31:37 |
| `data/processed/ca0001_modelo79_auditoria_descargas.csv` | Posible eliminar | Grupo 15 | Duplicado exacto de salida generada; validar antes de borrar si se usa como evidencia. | 698 | 2026-07-06 09:36:47 |
| `data/processed/ca0001_modelo79_bitacora_todas_ejecuciones.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 31350 | 2026-07-06 09:36:47 |
| `data/processed/ca0001_modelo79_canasta_congelada.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1968 | 2026-07-06 09:36:47 |
| `data/processed/ca0001_modelo79_coeficientes_congelados.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1538 | 2026-07-06 09:36:47 |
| `data/processed/ca0001_modelo79_detalle_estimaciones_run.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1710 | 2026-07-06 09:36:47 |
| `data/processed/ca0001_modelo79_manifiesto_modelo_congelado.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 7909 | 2026-07-06 09:36:47 |
| `data/processed/ca0001_modelo79_primer_pronostico_BACKUP_20260705_141424.csv` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 4214 | 2026-07-05 13:16:24 |
| `data/processed/ca0001_modelo79_primer_pronostico_congelado.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 3064 | 2026-07-06 09:36:47 |
| `data/processed/ca0001_modelo79_pronosticos_descartados_por_datos_incompletos.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 2978 | 2026-07-05 14:14:24 |
| `data/processed/ca0001_modelo79_snapshot_estimacion_actual.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 843 | 2026-07-06 09:36:47 |
| `data/processed/ca0001_modelo79a_correlaciones_finales.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 680 | 2026-07-05 11:59:02 |
| `data/processed/ca0001_modelo79c_auditoria_descargas.csv` | Posible eliminar | Grupo 15 | Duplicado exacto de salida generada; validar antes de borrar si se usa como evidencia. | 698 | 2026-07-06 09:36:55 |
| `data/processed/ca0001_modelo79c_contribuciones_ultima_fecha.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 4834 | 2026-07-06 09:36:55 |
| `data/processed/ca0001_modelo79c_ecuaciones_exactas.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 3050 | 2026-07-06 09:36:55 |
| `data/processed/ca0001_modelo79c_parametros_ecuaciones.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 5251 | 2026-07-06 09:36:55 |
| `data/processed/ca0001_modelo79c_resumen.json` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 4160 | 2026-07-06 09:36:55 |
| `data/processed/ca0001_modelo80_dashboard.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 7202 | 2026-07-06 09:36:38 |
| `data/processed/ca0001_modelo80_dashboard_REVISAR_20260705_124811.html` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 1712 | 2026-07-05 12:40:49 |
| `data/processed/ca0001_modelo80_metricas_prospectivas.csv` | Mantener | Grupo 14 | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 140 | 2026-07-06 09:36:38 |
| `data/processed/ca0001_modelo80_metricas_prospectivas_REVISAR_20260705_124811.csv` | Mover a archivo | Grupo 14 | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 140 | 2026-07-05 12:40:49 |
| `data/processed/ca0001_modelo80_sbs_oficial_detectado.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 3015 | 2026-07-06 09:36:37 |
| `data/processed/ca0001_modelo80_sbs_oficial_detectado_REVISAR_20260705_124811.csv` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 2591 | 2026-07-05 12:40:49 |
| `data/processed/ca0001_modelo80_ultima_respuesta_sbs.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 98746 | 2026-07-06 09:36:37 |
| `data/processed/ca0001_modelo80_ultima_respuesta_sbs_REVISAR_20260705_124811.html` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 98746 | 2026-07-05 12:40:49 |
| `data/processed/ca0001_modelo86_auditoria_descargas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 789 | 2026-07-05 14:20:10 |
| `data/processed/ca0001_modelo86_indicadores_intradia.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5656 | 2026-07-05 14:20:10 |
| `data/processed/ca0001_modelo86_indicadores_intradia.html` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 274104 | 2026-07-05 14:20:10 |
| `data/processed/ca0001_modelo86_resumen_intradia.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 258 | 2026-07-05 14:20:10 |
| `data/processed/ca0001_modelo92_indicadores_didacticos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3448 | 2026-07-05 22:50:08 |
| `data/processed/ca0001_modelo92_indicadores_didacticos.html` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 665990 | 2026-07-05 22:50:09 |
| `data/processed/ca0001_modelo97_simulador_monto_fondo3.html` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2130987 | 2026-07-05 22:55:03 |
| `data/processed/ca0001_modelo99_cuota_sintetica_intradia.html` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2340 | 2026-07-05 22:55:16 |
| `data/processed/ca0001_monitor_final_velas_diarias.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1525 | 2026-07-05 22:55:02 |
| `data/processed/ca0001_monitor_final_velas_diarias.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 111691 | 2026-07-05 22:55:02 |
| `data/processed/ca0001_monitor_fondo3_actualizado.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1242758 | 2026-07-06 09:36:57 |
| `data/processed/ca0001_monitor_practico_fondo3.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 76915 | 2026-07-05 21:17:31 |
| `data/processed/ca0001_monitor_practico_fondo3_v117.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 82378 | 2026-07-05 21:26:05 |
| `data/processed/ca0001_monitor_practico_fondo3_v118.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 85246 | 2026-07-05 21:32:03 |
| `data/processed/ca0001_monitor_practico_fondo3_v119.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 86059 | 2026-07-05 21:40:33 |
| `data/processed/ca0001_monitor_practico_fondo3_v120.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 587744 | 2026-07-05 21:46:59 |
| `data/processed/ca0001_monitor_practico_fondo3_v121.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 590224 | 2026-07-05 21:53:38 |
| `data/processed/ca0001_monitor_practico_fondo3_v122.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 594380 | 2026-07-05 22:03:05 |
| `data/processed/ca0001_monitor_practico_fondo3_v123.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 600391 | 2026-07-05 22:20:19 |
| `data/processed/ca0001_monitor_practico_fondo3_v124.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 603952 | 2026-07-05 22:28:27 |
| `data/processed/ca0001_monitor_practico_fondo3_v126.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1239235 | 2026-07-05 22:36:30 |
| `data/processed/ca0001_monitor_practico_fondo3_v127.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1241978 | 2026-07-05 22:46:07 |
| `data/processed/ca0001_monitor_practico_fondo3_v128.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1242713 | 2026-07-05 22:54:09 |
| `data/processed/ca0001_monitor_simple_fondo3.html` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 71763 | 2026-07-05 21:07:29 |
| `data/processed/ca0001_muestras_hojas_relevantes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 965221 | 2026-07-04 17:38:40 |
| `data/processed/ca0001_openfigi_cache_isin.json` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 8151775 | 2026-07-04 18:32:45 |
| `data/processed/ca0001_piloto_fondo3_ancho.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 331144 | 2026-07-04 17:44:25 |
| `data/processed/ca0001_piloto_fondo3_candidatos_detalle.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 432448 | 2026-07-04 17:44:25 |
| `data/processed/ca0001_piloto_fondo3_control_hojas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1095 | 2026-07-04 17:44:25 |
| `data/processed/ca0001_piloto_fondo3_errores.csv` | Posible eliminar | Grupo 1 | Duplicado exacto de salida generada; validar antes de borrar si se usa como evidencia. | 5 | 2026-07-04 17:44:25 |
| `data/processed/ca0001_piloto_fondo3_largo.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 575151 | 2026-07-04 17:44:25 |
| `data/processed/ca0001_piloto_fondo3_top_detalle.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 171224 | 2026-07-04 17:44:25 |
| `data/processed/ca0001_proxy_control_pesos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 48 | 2026-07-04 18:47:45 |
| `data/processed/ca0001_proxy_exposiciones_mensuales_ancho.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1270065 | 2026-07-04 18:47:45 |
| `data/processed/ca0001_proxy_exposiciones_mensuales_largo.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 5538453 | 2026-07-04 18:47:45 |
| `data/processed/ca0001_proxy_resumen_cobertura_variantes.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 7498 | 2026-07-04 18:47:45 |
| `data/processed/ca0001_proxy_resumen_ventanas.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1778 | 2026-07-04 18:47:45 |
| `data/processed/ca0001_proxy_turnover_factores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 185730 | 2026-07-04 18:47:45 |
| `data/processed/ca0001_proxy_ventanas_publicacion_45d.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1395836 | 2026-07-04 18:47:45 |
| `data/processed/ca0001_resumen_estructura_ultimo_archivo.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 712 | 2026-07-04 17:40:16 |
| `data/processed/ca0001_taxonomia_cambios_refinamiento.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 116647 | 2026-07-04 18:44:31 |
| `data/processed/ca0001_taxonomia_cobertura_mensual.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 336958 | 2026-07-04 18:41:23 |
| `data/processed/ca0001_taxonomia_comparacion_cobertura.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 6250 | 2026-07-04 18:44:31 |
| `data/processed/ca0001_taxonomia_control_pesos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 106905 | 2026-07-04 18:41:23 |
| `data/processed/ca0001_taxonomia_instrumentos_preliminar.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 260560 | 2026-07-04 18:41:22 |
| `data/processed/ca0001_taxonomia_instrumentos_refinada.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 379665 | 2026-07-04 18:44:31 |
| `data/processed/ca0001_taxonomia_pendientes_priorizados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 176681 | 2026-07-04 18:41:23 |
| `data/processed/ca0001_taxonomia_refinada_cobertura_mensual.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 335352 | 2026-07-04 18:44:31 |
| `data/processed/ca0001_taxonomia_refinada_control_pesos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 106682 | 2026-07-04 18:44:31 |
| `data/processed/ca0001_taxonomia_refinada_pendientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 170869 | 2026-07-04 18:44:31 |
| `data/processed/ca0001_taxonomia_refinada_resumen_cobertura.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 5936 | 2026-07-04 18:44:31 |
| `data/processed/ca0001_taxonomia_resumen_cobertura.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 5934 | 2026-07-04 18:41:23 |
| `data/processed/fondo3_atribucion_con_rezagos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 7402 | 2026-07-04 17:08:19 |
| `data/processed/fondo3_atribucion_con_rezagos_resumen.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 653 | 2026-07-04 17:08:19 |
| `data/processed/fondo3_atribucion_corregida_ultima_fecha.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 26884 | 2026-07-04 17:04:39 |
| `data/processed/fondo3_atribucion_dinamica_mensual.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3199798 | 2026-07-04 16:59:12 |
| `data/processed/fondo3_atribucion_parametros.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 125 | 2026-07-04 16:59:12 |
| `data/processed/fondo3_atribucion_ultima_fecha.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 30112 | 2026-07-04 16:59:12 |
| `data/processed/fondo3_cobertura_fechas_mercados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 125 | 2026-07-04 16:45:56 |
| `data/processed/fondo3_comparacion_metodos_fx.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2029 | 2026-07-04 17:04:39 |
| `data/processed/fondo3_comparacion_rezagos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3271 | 2026-07-04 17:08:19 |
| `data/processed/fondo3_correlaciones_factores_rezagos.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 55230 | 2026-07-04 16:45:56 |
| `data/processed/fondo3_estabilidad_factores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 24433 | 2026-07-04 16:59:12 |
| `data/processed/fondo3_mejor_rezago_por_afp.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 558 | 2026-07-04 17:08:19 |
| `data/processed/fondo3_mejor_rezago_por_factor.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 13936 | 2026-07-04 16:45:56 |
| `data/processed/fondo3_modelos_pesos_reales_anual.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3181 | 2026-07-04 17:31:38 |
| `data/processed/fondo3_modelos_pesos_reales_bootstrap.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1615 | 2026-07-04 17:31:38 |
| `data/processed/fondo3_modelos_pesos_reales_coeficientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 31840 | 2026-07-04 17:31:38 |
| `data/processed/fondo3_modelos_pesos_reales_metricas.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 2144 | 2026-07-04 17:31:38 |
| `data/processed/fondo3_modelos_pesos_reales_predicciones.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 656509 | 2026-07-04 17:31:38 |
| `data/processed/fondo3_pesos_cobertura.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 428 | 2026-07-04 17:31:38 |
| `data/processed/fondo3_pesos_diarios_aplicados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2323927 | 2026-07-04 17:31:38 |
| `data/processed/fondo3_resumen_corregido_ultima_fecha.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 1524 | 2026-07-04 17:04:39 |
| `data/processed/fondo3_robustez_pesos_anual.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 9732 | 2026-07-04 17:35:24 |
| `data/processed/fondo3_robustez_pesos_bootstrap.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 7169 | 2026-07-04 17:35:24 |
| `data/processed/fondo3_robustez_pesos_escenarios_metricas.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 6234 | 2026-07-04 17:35:24 |
| `data/processed/fondo3_robustez_pesos_predicciones.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 1657405 | 2026-07-04 17:35:24 |
| `data/processed/fondo3_top_factores_por_afp.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 7734 | 2026-07-04 16:45:56 |
| `data/processed/fp1356_candidatos_encabezado.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 7759 | 2026-07-04 17:16:11 |
| `data/processed/fp1356_cartera_economica_control.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 53798 | 2026-07-04 17:25:26 |
| `data/processed/fp1356_cartera_economica_control_v2.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 52874 | 2026-07-04 17:28:24 |
| `data/processed/fp1356_cartera_economica_detalle.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 8890900 | 2026-07-04 17:25:26 |
| `data/processed/fp1356_cartera_economica_detalle_v2.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 9729080 | 2026-07-04 17:28:24 |
| `data/processed/fp1356_cartera_economica_mensual.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1074902 | 2026-07-04 17:25:26 |
| `data/processed/fp1356_cartera_economica_mensual_v2.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1212843 | 2026-07-04 17:28:24 |
| `data/processed/fp1356_cartera_no_mapeada.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1756041 | 2026-07-04 17:25:26 |
| `data/processed/fp1356_cartera_no_mapeada_v2.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 363837 | 2026-07-04 17:28:24 |
| `data/processed/fp1356_catalogo_instrumentos_frecuencia.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 27268 | 2026-07-04 17:21:54 |
| `data/processed/fp1356_catalogo_mapeo_aplicado.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 31650 | 2026-07-04 17:25:26 |
| `data/processed/fp1356_catalogo_mapeo_aplicado_v2.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 35822 | 2026-07-04 17:28:24 |
| `data/processed/fp1356_coincidencias_estructura.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 11933 | 2026-07-04 17:12:50 |
| `data/processed/fp1356_comparacion_mapeo_v1_v2.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 29759 | 2026-07-04 17:28:24 |
| `data/processed/fp1356_control_sumas_mensuales.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 31751 | 2026-07-04 17:21:54 |
| `data/processed/fp1356_descripciones_para_mapeo.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 28040 | 2026-07-04 17:21:54 |
| `data/processed/fp1356_errores_inspeccion.csv` | Posible eliminar | Grupo 1 | Duplicado exacto de salida generada; validar antes de borrar si se usa como evidencia. | 5 | 2026-07-04 17:12:50 |
| `data/processed/fp1356_fondo3_cartera_largo.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 9412429 | 2026-07-04 17:19:51 |
| `data/processed/fp1356_fondo3_catalogo_descripciones.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 27762 | 2026-07-04 17:19:52 |
| `data/processed/fp1356_fondo3_control_calidad.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 19348 | 2026-07-04 17:19:52 |
| `data/processed/fp1356_fondo3_errores.csv` | Posible eliminar | Grupo 1 | Duplicado exacto de salida generada; validar antes de borrar si se usa como evidencia. | 5 | 2026-07-04 17:19:52 |
| `data/processed/fp1356_fondo3_instrumentos_hoja.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 7772556 | 2026-07-04 17:19:52 |
| `data/processed/fp1356_fondo3_resumen_nivel1.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 340287 | 2026-07-04 17:19:52 |
| `data/processed/fp1356_inventario_archivos_inspeccionados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1093 | 2026-07-04 17:12:50 |
| `data/processed/fp1356_inventario_enlaces.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 16178 | 2026-07-04 17:12:49 |
| `data/processed/fp1356_inventario_hojas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2340 | 2026-07-04 17:12:50 |
| `data/processed/fp1356_resumen_nivel2_ultimo_mes.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 9947 | 2026-07-04 17:21:54 |
| `data/processed/fp1356_top_instrumentos_ultimo_mes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 26219 | 2026-07-04 17:21:54 |
| `data/processed/fp1356_vista_completa_ultimos3.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 32924 | 2026-07-04 17:16:11 |
| `data/processed/fp1356_vista_ultimo_fondo3.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 11115 | 2026-07-04 17:16:11 |
| `data/processed/graficos_modelo52/modelo52_habitat_error_diario.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 195723 | 2026-07-04 20:22:42 |
| `data/processed/graficos_modelo52/modelo52_habitat_sbs_vs_estimado_1d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 139695 | 2026-07-04 20:22:42 |
| `data/processed/graficos_modelo52/modelo52_habitat_trayectoria_acumulada.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 144161 | 2026-07-04 20:22:42 |
| `data/processed/graficos_modelo52/modelo52_integra_error_diario.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 192897 | 2026-07-04 20:22:43 |
| `data/processed/graficos_modelo52/modelo52_integra_sbs_vs_estimado_1d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 146603 | 2026-07-04 20:22:43 |
| `data/processed/graficos_modelo52/modelo52_integra_trayectoria_acumulada.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 151465 | 2026-07-04 20:22:43 |
| `data/processed/graficos_modelo52/modelo52_prima_error_diario.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 187209 | 2026-07-04 20:22:43 |
| `data/processed/graficos_modelo52/modelo52_prima_sbs_vs_estimado_1d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 143183 | 2026-07-04 20:22:43 |
| `data/processed/graficos_modelo52/modelo52_prima_trayectoria_acumulada.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 150687 | 2026-07-04 20:22:43 |
| `data/processed/graficos_modelo52/modelo52_profuturo_error_diario.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 191837 | 2026-07-04 20:22:44 |
| `data/processed/graficos_modelo52/modelo52_profuturo_sbs_vs_estimado_1d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 153955 | 2026-07-04 20:22:43 |
| `data/processed/graficos_modelo52/modelo52_profuturo_trayectoria_acumulada.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 156628 | 2026-07-04 20:22:43 |
| `data/processed/graficos_modelo53/modelo53_habitat_desfase_4d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 149027 | 2026-07-04 20:25:35 |
| `data/processed/graficos_modelo53/modelo53_habitat_desfase_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 148524 | 2026-07-04 20:25:36 |
| `data/processed/graficos_modelo53/modelo53_habitat_error_desfase_4d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 164748 | 2026-07-04 20:25:36 |
| `data/processed/graficos_modelo53/modelo53_habitat_error_desfase_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 155937 | 2026-07-04 20:25:36 |
| `data/processed/graficos_modelo53/modelo53_integra_desfase_4d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 157073 | 2026-07-04 20:25:36 |
| `data/processed/graficos_modelo53/modelo53_integra_desfase_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 157358 | 2026-07-04 20:25:36 |
| `data/processed/graficos_modelo53/modelo53_integra_error_desfase_4d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 163262 | 2026-07-04 20:25:36 |
| `data/processed/graficos_modelo53/modelo53_integra_error_desfase_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 154355 | 2026-07-04 20:25:36 |
| `data/processed/graficos_modelo53/modelo53_prima_desfase_4d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 152495 | 2026-07-04 20:25:37 |
| `data/processed/graficos_modelo53/modelo53_prima_desfase_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 152809 | 2026-07-04 20:25:37 |
| `data/processed/graficos_modelo53/modelo53_prima_error_desfase_4d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 150900 | 2026-07-04 20:25:37 |
| `data/processed/graficos_modelo53/modelo53_prima_error_desfase_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 145349 | 2026-07-04 20:25:37 |
| `data/processed/graficos_modelo53/modelo53_profuturo_desfase_4d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 165575 | 2026-07-04 20:25:37 |
| `data/processed/graficos_modelo53/modelo53_profuturo_desfase_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 165170 | 2026-07-04 20:25:37 |
| `data/processed/graficos_modelo53/modelo53_profuturo_error_desfase_4d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 171635 | 2026-07-04 20:25:37 |
| `data/processed/graficos_modelo53/modelo53_profuturo_error_desfase_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 169084 | 2026-07-04 20:25:37 |
| `data/processed/graficos_modelo56/modelo56_habitat_error_estimacion_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 170566 | 2026-07-04 20:38:27 |
| `data/processed/graficos_modelo56/modelo56_habitat_sbs_vs_estimacion_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 153668 | 2026-07-04 20:38:27 |
| `data/processed/graficos_modelo56/modelo56_habitat_ultima_ventana_oculta.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 85044 | 2026-07-04 20:38:27 |
| `data/processed/graficos_modelo56/modelo56_integra_error_estimacion_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 180264 | 2026-07-04 20:38:28 |
| `data/processed/graficos_modelo56/modelo56_integra_sbs_vs_estimacion_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 160667 | 2026-07-04 20:38:28 |
| `data/processed/graficos_modelo56/modelo56_integra_ultima_ventana_oculta.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 85258 | 2026-07-04 20:38:28 |
| `data/processed/graficos_modelo56/modelo56_prima_error_estimacion_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 164848 | 2026-07-04 20:38:28 |
| `data/processed/graficos_modelo56/modelo56_prima_sbs_vs_estimacion_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 157005 | 2026-07-04 20:38:28 |
| `data/processed/graficos_modelo56/modelo56_prima_ultima_ventana_oculta.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 88684 | 2026-07-04 20:38:28 |
| `data/processed/graficos_modelo56/modelo56_profuturo_error_estimacion_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 187560 | 2026-07-04 20:38:28 |
| `data/processed/graficos_modelo56/modelo56_profuturo_sbs_vs_estimacion_5d.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 168848 | 2026-07-04 20:38:28 |
| `data/processed/graficos_modelo56/modelo56_profuturo_ultima_ventana_oculta.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 87940 | 2026-07-04 20:38:29 |
| `data/processed/graficos_modelo57/modelo57_habitat_oficial_y_estimado.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 126982 | 2026-07-04 22:51:12 |
| `data/processed/graficos_modelo57/modelo57_integra_oficial_y_estimado.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 132939 | 2026-07-04 22:51:12 |
| `data/processed/graficos_modelo57/modelo57_prima_oficial_y_estimado.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 131540 | 2026-07-04 22:51:12 |
| `data/processed/graficos_modelo57/modelo57_profuturo_oficial_y_estimado.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 145347 | 2026-07-04 22:51:12 |
| `data/processed/graficos_modelo59/modelo59_comparacion_senal_afp.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 47587 | 2026-07-04 22:51:15 |
| `data/processed/graficos_modelo59/modelo59_habitat_panel_operativo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 137732 | 2026-07-04 22:51:14 |
| `data/processed/graficos_modelo59/modelo59_integra_panel_operativo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 144515 | 2026-07-04 22:51:14 |
| `data/processed/graficos_modelo59/modelo59_prima_panel_operativo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 142297 | 2026-07-04 22:51:14 |
| `data/processed/graficos_modelo59/modelo59_profuturo_panel_operativo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 153526 | 2026-07-04 22:51:15 |
| `data/processed/graficos_modelo62/01_heatmap_correlaciones_spearman_train.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 49733 | 2026-07-04 23:04:19 |
| `data/processed/graficos_modelo62/02_base100_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 111772 | 2026-07-04 23:04:14 |
| `data/processed/graficos_modelo62/02_base100_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 114694 | 2026-07-04 23:04:15 |
| `data/processed/graficos_modelo62/02_base100_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 150700 | 2026-07-04 23:04:17 |
| `data/processed/graficos_modelo62/02_base100_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 114949 | 2026-07-04 23:04:19 |
| `data/processed/graficos_modelo62/03_correlacion_rezagos_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 61692 | 2026-07-04 23:04:20 |
| `data/processed/graficos_modelo62/03_correlacion_rezagos_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 76672 | 2026-07-04 23:04:20 |
| `data/processed/graficos_modelo62/03_correlacion_rezagos_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 80245 | 2026-07-04 23:04:20 |
| `data/processed/graficos_modelo62/03_correlacion_rezagos_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 75536 | 2026-07-04 23:04:20 |
| `data/processed/graficos_modelo62/04_histograma_retornos_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 34556 | 2026-07-04 23:04:14 |
| `data/processed/graficos_modelo62/04_histograma_retornos_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 34401 | 2026-07-04 23:04:15 |
| `data/processed/graficos_modelo62/04_histograma_retornos_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 34299 | 2026-07-04 23:04:17 |
| `data/processed/graficos_modelo62/04_histograma_retornos_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 36644 | 2026-07-04 23:04:19 |
| `data/processed/graficos_modelo62/05_qq_retornos_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 54417 | 2026-07-04 23:04:14 |
| `data/processed/graficos_modelo62/05_qq_retornos_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 54464 | 2026-07-04 23:04:15 |
| `data/processed/graficos_modelo62/05_qq_retornos_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 54111 | 2026-07-04 23:04:18 |
| `data/processed/graficos_modelo62/05_qq_retornos_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 53441 | 2026-07-04 23:04:19 |
| `data/processed/graficos_modelo62/06_acf_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 32622 | 2026-07-04 23:04:14 |
| `data/processed/graficos_modelo62/06_acf_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 32475 | 2026-07-04 23:04:15 |
| `data/processed/graficos_modelo62/06_acf_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 32001 | 2026-07-04 23:04:18 |
| `data/processed/graficos_modelo62/06_acf_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 32694 | 2026-07-04 23:04:19 |
| `data/processed/graficos_modelo62/07_pacf_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 31936 | 2026-07-04 23:04:14 |
| `data/processed/graficos_modelo62/07_pacf_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 31956 | 2026-07-04 23:04:16 |
| `data/processed/graficos_modelo62/07_pacf_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 31817 | 2026-07-04 23:04:18 |
| `data/processed/graficos_modelo62/07_pacf_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 32416 | 2026-07-04 23:04:19 |
| `data/processed/graficos_modelo62/08_scatter_habitat_copx.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 138460 | 2026-07-04 23:04:13 |
| `data/processed/graficos_modelo62/08_scatter_habitat_idx_vix.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 134243 | 2026-07-04 23:04:13 |
| `data/processed/graficos_modelo62/08_scatter_integra_copx.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 131556 | 2026-07-04 23:04:14 |
| `data/processed/graficos_modelo62/08_scatter_integra_epu.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 134127 | 2026-07-04 23:04:15 |
| `data/processed/graficos_modelo62/08_scatter_prima_copx.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 132867 | 2026-07-04 23:04:16 |
| `data/processed/graficos_modelo62/08_scatter_prima_epu.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 131058 | 2026-07-04 23:04:16 |
| `data/processed/graficos_modelo62/08_scatter_prima_idx_vix.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 128364 | 2026-07-04 23:04:17 |
| `data/processed/graficos_modelo62/08_scatter_prima_xlb.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 127087 | 2026-07-04 23:04:17 |
| `data/processed/graficos_modelo62/08_scatter_profuturo_copx.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 138135 | 2026-07-04 23:04:18 |
| `data/processed/graficos_modelo62/08_scatter_profuturo_epu.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 137526 | 2026-07-04 23:04:18 |
| `data/processed/graficos_modelo62/09_corr_movil_habitat_copx.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 109978 | 2026-07-04 23:04:13 |
| `data/processed/graficos_modelo62/09_corr_movil_habitat_idx_vix.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 105044 | 2026-07-04 23:04:13 |
| `data/processed/graficos_modelo62/09_corr_movil_integra_copx.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 108985 | 2026-07-04 23:04:14 |
| `data/processed/graficos_modelo62/09_corr_movil_integra_epu.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 108699 | 2026-07-04 23:04:15 |
| `data/processed/graficos_modelo62/09_corr_movil_prima_copx.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 110052 | 2026-07-04 23:04:16 |
| `data/processed/graficos_modelo62/09_corr_movil_prima_epu.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 109213 | 2026-07-04 23:04:16 |
| `data/processed/graficos_modelo62/09_corr_movil_prima_idx_vix.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 106584 | 2026-07-04 23:04:17 |
| `data/processed/graficos_modelo62/09_corr_movil_prima_xlb.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 110833 | 2026-07-04 23:04:17 |
| `data/processed/graficos_modelo62/09_corr_movil_profuturo_copx.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 108504 | 2026-07-04 23:04:18 |
| `data/processed/graficos_modelo62/09_corr_movil_profuturo_epu.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 107822 | 2026-07-04 23:04:19 |
| `data/processed/graficos_modelo62/10_beta_movil_habitat_copx.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 134069 | 2026-07-04 23:04:14 |
| `data/processed/graficos_modelo62/10_beta_movil_habitat_idx_vix.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 119276 | 2026-07-04 23:04:13 |
| `data/processed/graficos_modelo62/10_beta_movil_integra_copx.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 128714 | 2026-07-04 23:04:15 |
| `data/processed/graficos_modelo62/10_beta_movil_integra_epu.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 135621 | 2026-07-04 23:04:15 |
| `data/processed/graficos_modelo62/10_beta_movil_prima_copx.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 125125 | 2026-07-04 23:04:16 |
| `data/processed/graficos_modelo62/10_beta_movil_prima_epu.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 132596 | 2026-07-04 23:04:16 |
| `data/processed/graficos_modelo62/10_beta_movil_prima_idx_vix.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 114551 | 2026-07-04 23:04:17 |
| `data/processed/graficos_modelo62/10_beta_movil_prima_xlb.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 132994 | 2026-07-04 23:04:17 |
| `data/processed/graficos_modelo62/10_beta_movil_profuturo_copx.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 122802 | 2026-07-04 23:04:18 |
| `data/processed/graficos_modelo62/10_beta_movil_profuturo_epu.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 129271 | 2026-07-04 23:04:19 |
| `data/processed/graficos_modelo63/01_mae_rmse_prueba_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 60052 | 2026-07-04 23:19:59 |
| `data/processed/graficos_modelo63/01_mae_rmse_prueba_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 60646 | 2026-07-04 23:19:59 |
| `data/processed/graficos_modelo63/01_mae_rmse_prueba_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 61532 | 2026-07-04 23:20:00 |
| `data/processed/graficos_modelo63/01_mae_rmse_prueba_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 60767 | 2026-07-04 23:20:00 |
| `data/processed/graficos_modelo63/02_mape_p90_prueba_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 57652 | 2026-07-04 23:19:59 |
| `data/processed/graficos_modelo63/02_mape_p90_prueba_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 57908 | 2026-07-04 23:19:59 |
| `data/processed/graficos_modelo63/02_mape_p90_prueba_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 56957 | 2026-07-04 23:20:00 |
| `data/processed/graficos_modelo63/02_mape_p90_prueba_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 57457 | 2026-07-04 23:20:00 |
| `data/processed/graficos_modelo63/03_mape_segmentos_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 80777 | 2026-07-04 23:19:59 |
| `data/processed/graficos_modelo63/03_mape_segmentos_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 83579 | 2026-07-04 23:20:00 |
| `data/processed/graficos_modelo63/03_mape_segmentos_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 86228 | 2026-07-04 23:20:00 |
| `data/processed/graficos_modelo63/03_mape_segmentos_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 87109 | 2026-07-04 23:20:00 |
| `data/processed/graficos_modelo63_corregido/01_mae_rmse_entrenamiento_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 56680 | 2026-07-04 23:23:55 |
| `data/processed/graficos_modelo63_corregido/01_mae_rmse_entrenamiento_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 56559 | 2026-07-04 23:23:56 |
| `data/processed/graficos_modelo63_corregido/01_mae_rmse_entrenamiento_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 56260 | 2026-07-04 23:23:57 |
| `data/processed/graficos_modelo63_corregido/01_mae_rmse_entrenamiento_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 58336 | 2026-07-04 23:23:57 |
| `data/processed/graficos_modelo63_corregido/01_mae_rmse_prueba_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 54288 | 2026-07-04 23:23:56 |
| `data/processed/graficos_modelo63_corregido/01_mae_rmse_prueba_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 54900 | 2026-07-04 23:23:56 |
| `data/processed/graficos_modelo63_corregido/01_mae_rmse_prueba_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 55637 | 2026-07-04 23:23:57 |
| `data/processed/graficos_modelo63_corregido/01_mae_rmse_prueba_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 55146 | 2026-07-04 23:23:58 |
| `data/processed/graficos_modelo63_corregido/01_mae_rmse_validacion_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 57677 | 2026-07-04 23:23:55 |
| `data/processed/graficos_modelo63_corregido/01_mae_rmse_validacion_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 59928 | 2026-07-04 23:23:56 |
| `data/processed/graficos_modelo63_corregido/01_mae_rmse_validacion_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 56468 | 2026-07-04 23:23:57 |
| `data/processed/graficos_modelo63_corregido/01_mae_rmse_validacion_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 56957 | 2026-07-04 23:23:57 |
| `data/processed/graficos_modelo63_corregido/02_mape_p90_entrenamiento_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 52305 | 2026-07-04 23:23:55 |
| `data/processed/graficos_modelo63_corregido/02_mape_p90_entrenamiento_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 54020 | 2026-07-04 23:23:56 |
| `data/processed/graficos_modelo63_corregido/02_mape_p90_entrenamiento_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 52251 | 2026-07-04 23:23:57 |
| `data/processed/graficos_modelo63_corregido/02_mape_p90_entrenamiento_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 53014 | 2026-07-04 23:23:57 |
| `data/processed/graficos_modelo63_corregido/02_mape_p90_prueba_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 49845 | 2026-07-04 23:23:56 |
| `data/processed/graficos_modelo63_corregido/02_mape_p90_prueba_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 50711 | 2026-07-04 23:23:56 |
| `data/processed/graficos_modelo63_corregido/02_mape_p90_prueba_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 50194 | 2026-07-04 23:23:57 |
| `data/processed/graficos_modelo63_corregido/02_mape_p90_prueba_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 50783 | 2026-07-04 23:23:58 |
| `data/processed/graficos_modelo63_corregido/02_mape_p90_validacion_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 53868 | 2026-07-04 23:23:56 |
| `data/processed/graficos_modelo63_corregido/02_mape_p90_validacion_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 54600 | 2026-07-04 23:23:56 |
| `data/processed/graficos_modelo63_corregido/02_mape_p90_validacion_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 53144 | 2026-07-04 23:23:57 |
| `data/processed/graficos_modelo63_corregido/02_mape_p90_validacion_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 53235 | 2026-07-04 23:23:57 |
| `data/processed/graficos_modelo64/01_mae_rmse_test_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 64769 | 2026-07-04 23:44:00 |
| `data/processed/graficos_modelo64/01_mae_rmse_test_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 67222 | 2026-07-04 23:44:01 |
| `data/processed/graficos_modelo64/01_mae_rmse_test_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 66978 | 2026-07-04 23:44:02 |
| `data/processed/graficos_modelo64/01_mae_rmse_test_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 67774 | 2026-07-04 23:44:03 |
| `data/processed/graficos_modelo64/02_mape_p90_test_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 60152 | 2026-07-04 23:44:01 |
| `data/processed/graficos_modelo64/02_mape_p90_test_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 60448 | 2026-07-04 23:44:01 |
| `data/processed/graficos_modelo64/02_mape_p90_test_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 59935 | 2026-07-04 23:44:02 |
| `data/processed/graficos_modelo64/02_mape_p90_test_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 60283 | 2026-07-04 23:44:03 |
| `data/processed/graficos_modelo64/03_retorno_real_estimado_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 191570 | 2026-07-04 23:44:01 |
| `data/processed/graficos_modelo64/03_retorno_real_estimado_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 208986 | 2026-07-04 23:44:02 |
| `data/processed/graficos_modelo64/03_retorno_real_estimado_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 187437 | 2026-07-04 23:44:02 |
| `data/processed/graficos_modelo64/03_retorno_real_estimado_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 196947 | 2026-07-04 23:44:03 |
| `data/processed/graficos_modelo64/04_residuos_histograma_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 30011 | 2026-07-04 23:44:01 |
| `data/processed/graficos_modelo64/04_residuos_histograma_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 29876 | 2026-07-04 23:44:02 |
| `data/processed/graficos_modelo64/04_residuos_histograma_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 29668 | 2026-07-04 23:44:02 |
| `data/processed/graficos_modelo64/04_residuos_histograma_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 31949 | 2026-07-04 23:44:03 |
| `data/processed/graficos_modelo64/05_residuos_acf_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 32126 | 2026-07-04 23:44:01 |
| `data/processed/graficos_modelo64/05_residuos_acf_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 32207 | 2026-07-04 23:44:02 |
| `data/processed/graficos_modelo64/05_residuos_acf_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 31662 | 2026-07-04 23:44:03 |
| `data/processed/graficos_modelo64/05_residuos_acf_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 32294 | 2026-07-04 23:44:03 |
| `data/processed/graficos_modelo64/06_cuota_real_estimada_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 112184 | 2026-07-04 23:44:01 |
| `data/processed/graficos_modelo64/06_cuota_real_estimada_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 119827 | 2026-07-04 23:44:02 |
| `data/processed/graficos_modelo64/06_cuota_real_estimada_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 116530 | 2026-07-04 23:44:03 |
| `data/processed/graficos_modelo64/06_cuota_real_estimada_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 125899 | 2026-07-04 23:44:03 |
| `data/processed/graficos_modelo64/07_heatmap_mape_test.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 104386 | 2026-07-04 23:44:04 |
| `data/processed/graficos_modelo65/01_r2_test_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 57308 | 2026-07-05 00:09:08 |
| `data/processed/graficos_modelo65/01_r2_test_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 58526 | 2026-07-05 00:09:09 |
| `data/processed/graficos_modelo65/01_r2_test_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 60108 | 2026-07-05 00:09:11 |
| `data/processed/graficos_modelo65/01_r2_test_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 59106 | 2026-07-05 00:09:14 |
| `data/processed/graficos_modelo65/02_mape_p90_test_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 60588 | 2026-07-05 00:09:08 |
| `data/processed/graficos_modelo65/02_mape_p90_test_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 56730 | 2026-07-05 00:09:10 |
| `data/processed/graficos_modelo65/02_mape_p90_test_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 56728 | 2026-07-05 00:09:12 |
| `data/processed/graficos_modelo65/02_mape_p90_test_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 57293 | 2026-07-05 00:09:14 |
| `data/processed/graficos_modelo65/03_retorno_habitat_arimax_000.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 185326 | 2026-07-05 00:09:08 |
| `data/processed/graficos_modelo65/03_retorno_habitat_ew_ridge_hl60_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 184481 | 2026-07-05 00:09:09 |
| `data/processed/graficos_modelo65/03_retorno_habitat_rolling_ridge_w250_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 194235 | 2026-07-05 00:09:09 |
| `data/processed/graficos_modelo65/03_retorno_integra_arimax_000.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 202157 | 2026-07-05 00:09:10 |
| `data/processed/graficos_modelo65/03_retorno_integra_ew_ridge_hl120_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 208758 | 2026-07-05 00:09:11 |
| `data/processed/graficos_modelo65/03_retorno_integra_rolling_ridge_w1000_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 209835 | 2026-07-05 00:09:10 |
| `data/processed/graficos_modelo65/03_retorno_prima_arimax_000.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 182522 | 2026-07-05 00:09:12 |
| `data/processed/graficos_modelo65/03_retorno_prima_ew_ridge_hl250_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 189619 | 2026-07-05 00:09:13 |
| `data/processed/graficos_modelo65/03_retorno_prima_rolling_ridge_w1000_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 190490 | 2026-07-05 00:09:13 |
| `data/processed/graficos_modelo65/03_retorno_profuturo_arimax_000.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 192172 | 2026-07-05 00:09:14 |
| `data/processed/graficos_modelo65/03_retorno_profuturo_ew_ridge_hl250_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 196772 | 2026-07-05 00:09:15 |
| `data/processed/graficos_modelo65/03_retorno_profuturo_rolling_ridge_w1000_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 197974 | 2026-07-05 00:09:14 |
| `data/processed/graficos_modelo65/04_cuota_habitat_arimax_000.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 109035 | 2026-07-05 00:09:08 |
| `data/processed/graficos_modelo65/04_cuota_habitat_ew_ridge_hl60_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 111224 | 2026-07-05 00:09:09 |
| `data/processed/graficos_modelo65/04_cuota_habitat_rolling_ridge_w250_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 113764 | 2026-07-05 00:09:09 |
| `data/processed/graficos_modelo65/04_cuota_integra_arimax_000.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 115662 | 2026-07-05 00:09:10 |
| `data/processed/graficos_modelo65/04_cuota_integra_ew_ridge_hl120_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 117699 | 2026-07-05 00:09:11 |
| `data/processed/graficos_modelo65/04_cuota_integra_rolling_ridge_w1000_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 120017 | 2026-07-05 00:09:11 |
| `data/processed/graficos_modelo65/04_cuota_prima_arimax_000.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 112192 | 2026-07-05 00:09:12 |
| `data/processed/graficos_modelo65/04_cuota_prima_ew_ridge_hl250_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 114695 | 2026-07-05 00:09:13 |
| `data/processed/graficos_modelo65/04_cuota_prima_rolling_ridge_w1000_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 116950 | 2026-07-05 00:09:13 |
| `data/processed/graficos_modelo65/04_cuota_profuturo_arimax_000.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 121771 | 2026-07-05 00:09:14 |
| `data/processed/graficos_modelo65/04_cuota_profuturo_ew_ridge_hl250_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 124093 | 2026-07-05 00:09:15 |
| `data/processed/graficos_modelo65/04_cuota_profuturo_rolling_ridge_w1000_a0.001.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 126040 | 2026-07-05 00:09:15 |
| `data/processed/graficos_modelo66/01_mape_p90_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 97240 | 2026-07-05 00:54:32 |
| `data/processed/graficos_modelo66/01_mape_p90_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 97458 | 2026-07-05 00:54:34 |
| `data/processed/graficos_modelo66/01_mape_p90_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 97340 | 2026-07-05 00:54:34 |
| `data/processed/graficos_modelo66/01_mape_p90_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 97706 | 2026-07-05 00:54:35 |
| `data/processed/graficos_modelo66/02_cuota_ganador_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 105331 | 2026-07-05 00:54:33 |
| `data/processed/graficos_modelo66/02_cuota_ganador_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 116732 | 2026-07-05 00:54:34 |
| `data/processed/graficos_modelo66/02_cuota_ganador_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 113471 | 2026-07-05 00:54:34 |
| `data/processed/graficos_modelo66/02_cuota_ganador_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 121999 | 2026-07-05 00:54:35 |
| `data/processed/graficos_modelo66/03_scatter_ganador_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 86248 | 2026-07-05 00:54:34 |
| `data/processed/graficos_modelo66/03_scatter_ganador_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 91639 | 2026-07-05 00:54:34 |
| `data/processed/graficos_modelo66/03_scatter_ganador_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 88684 | 2026-07-05 00:54:34 |
| `data/processed/graficos_modelo66/03_scatter_ganador_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 90625 | 2026-07-05 00:54:35 |
| `data/processed/graficos_modelo66/04_importancia_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 61979 | 2026-07-05 00:54:34 |
| `data/processed/graficos_modelo66/04_importancia_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 64975 | 2026-07-05 00:54:35 |
| `data/processed/graficos_modelo66/04_importancia_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 62330 | 2026-07-05 00:54:35 |
| `data/processed/graficos_modelo67/01_cuota_ensemble_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 123979 | 2026-07-05 01:00:56 |
| `data/processed/graficos_modelo67/01_cuota_ensemble_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 135929 | 2026-07-05 01:00:57 |
| `data/processed/graficos_modelo67/01_cuota_ensemble_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 130048 | 2026-07-05 01:00:57 |
| `data/processed/graficos_modelo67/01_cuota_ensemble_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 146859 | 2026-07-05 01:00:58 |
| `data/processed/graficos_modelo67/02_mape_movil_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 125470 | 2026-07-05 01:00:56 |
| `data/processed/graficos_modelo67/02_mape_movil_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 134781 | 2026-07-05 01:00:57 |
| `data/processed/graficos_modelo67/02_mape_movil_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 124752 | 2026-07-05 01:00:57 |
| `data/processed/graficos_modelo67/02_mape_movil_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 130805 | 2026-07-05 01:00:58 |
| `data/processed/graficos_modelo68/01_cuota_calibrada_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 121496 | 2026-07-05 01:05:52 |
| `data/processed/graficos_modelo68/01_cuota_calibrada_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 123450 | 2026-07-05 01:06:19 |
| `data/processed/graficos_modelo68/01_cuota_calibrada_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 119172 | 2026-07-05 01:06:46 |
| `data/processed/graficos_modelo68/01_cuota_calibrada_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 141202 | 2026-07-05 01:07:17 |
| `data/processed/graficos_modelo68/02_escala_dinamica_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 76798 | 2026-07-05 01:05:52 |
| `data/processed/graficos_modelo68/02_escala_dinamica_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 32281 | 2026-07-05 01:06:19 |
| `data/processed/graficos_modelo68/02_escala_dinamica_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 31744 | 2026-07-05 01:06:46 |
| `data/processed/graficos_modelo68/02_escala_dinamica_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 79330 | 2026-07-05 01:07:17 |
| `data/processed/graficos_modelo68/03_mape_movil_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 123832 | 2026-07-05 01:05:52 |
| `data/processed/graficos_modelo68/03_mape_movil_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 104886 | 2026-07-05 01:06:19 |
| `data/processed/graficos_modelo68/03_mape_movil_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 100473 | 2026-07-05 01:06:46 |
| `data/processed/graficos_modelo68/03_mape_movil_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 130291 | 2026-07-05 01:07:17 |
| `data/processed/graficos_modelo69/01_top_factores_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 90503 | 2026-07-05 01:30:57 |
| `data/processed/graficos_modelo69/01_top_factores_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 91141 | 2026-07-05 01:30:57 |
| `data/processed/graficos_modelo69/01_top_factores_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 90751 | 2026-07-05 01:30:57 |
| `data/processed/graficos_modelo69/01_top_factores_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 91829 | 2026-07-05 01:30:58 |
| `data/processed/graficos_modelo70/01_cuota_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 116866 | 2026-07-05 02:12:19 |
| `data/processed/graficos_modelo70/01_cuota_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 123253 | 2026-07-05 02:15:48 |
| `data/processed/graficos_modelo70/01_cuota_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 120450 | 2026-07-05 02:21:26 |
| `data/processed/graficos_modelo70/01_cuota_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 131286 | 2026-07-05 02:26:25 |
| `data/processed/graficos_modelo71/01_acciones_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 115301 | 2026-07-05 09:26:35 |
| `data/processed/graficos_modelo71/01_acciones_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 123127 | 2026-07-05 09:29:10 |
| `data/processed/graficos_modelo71/01_acciones_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 122710 | 2026-07-05 09:32:56 |
| `data/processed/graficos_modelo71/01_acciones_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 132119 | 2026-07-05 09:36:41 |
| `data/processed/graficos_modelo72/01_bvl_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 77297 | 2026-07-05 09:52:15 |
| `data/processed/graficos_modelo72/01_bvl_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 77965 | 2026-07-05 09:52:15 |
| `data/processed/graficos_modelo72/01_bvl_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 77410 | 2026-07-05 09:52:15 |
| `data/processed/graficos_modelo72/01_bvl_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 76657 | 2026-07-05 09:52:15 |
| `data/processed/graficos_modelo73/01_cuota_bvl_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 116823 | 2026-07-05 10:13:03 |
| `data/processed/graficos_modelo73/01_cuota_bvl_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 125847 | 2026-07-05 10:15:34 |
| `data/processed/graficos_modelo73/01_cuota_bvl_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 123646 | 2026-07-05 10:18:52 |
| `data/processed/graficos_modelo73/01_cuota_bvl_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 133291 | 2026-07-05 10:22:57 |
| `data/processed/graficos_modelo74/01_indices_nativos_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 155099 | 2026-07-05 10:26:31 |
| `data/processed/graficos_modelo74/01_indices_nativos_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 157026 | 2026-07-05 10:26:31 |
| `data/processed/graficos_modelo74/01_indices_nativos_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 155296 | 2026-07-05 10:26:31 |
| `data/processed/graficos_modelo74/01_indices_nativos_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 158207 | 2026-07-05 10:26:31 |
| `data/processed/graficos_modelo75/01_indices_vs_etf_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 115062 | 2026-07-05 10:43:23 |
| `data/processed/graficos_modelo75/01_indices_vs_etf_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 122336 | 2026-07-05 10:46:22 |
| `data/processed/graficos_modelo75/01_indices_vs_etf_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 124318 | 2026-07-05 10:50:29 |
| `data/processed/graficos_modelo75/01_indices_vs_etf_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 127417 | 2026-07-05 10:52:14 |
| `data/processed/graficos_modelo76/01_futuros_cripto_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 149947 | 2026-07-05 10:53:48 |
| `data/processed/graficos_modelo76/01_futuros_cripto_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 149740 | 2026-07-05 10:53:48 |
| `data/processed/graficos_modelo76/01_futuros_cripto_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 150644 | 2026-07-05 10:53:49 |
| `data/processed/graficos_modelo76/01_futuros_cripto_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 152255 | 2026-07-05 10:53:49 |
| `data/processed/graficos_modelo77/01_mod76_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 114421 | 2026-07-05 11:09:25 |
| `data/processed/graficos_modelo77/01_mod76_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 124006 | 2026-07-05 11:13:50 |
| `data/processed/graficos_modelo77/01_mod76_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 121604 | 2026-07-05 11:18:19 |
| `data/processed/graficos_modelo77/01_mod76_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 129474 | 2026-07-05 11:21:49 |
| `data/processed/graficos_modelo78/01_poda_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 114280 | 2026-07-05 11:30:31 |
| `data/processed/graficos_modelo78/01_poda_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 120158 | 2026-07-05 11:30:48 |
| `data/processed/graficos_modelo78/01_poda_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 118557 | 2026-07-05 11:31:01 |
| `data/processed/graficos_modelo78/01_poda_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 128885 | 2026-07-05 11:31:37 |
| `data/processed/graficos_modelo79a/01_real_vs_estimada_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 113909 | 2026-07-05 11:59:01 |
| `data/processed/graficos_modelo79a/01_real_vs_estimada_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 120759 | 2026-07-05 11:59:01 |
| `data/processed/graficos_modelo79a/01_real_vs_estimada_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 119264 | 2026-07-05 11:59:02 |
| `data/processed/graficos_modelo79a/01_real_vs_estimada_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 126968 | 2026-07-05 11:59:02 |
| `data/processed/graficos_modelo79a/02_scatter_retorno_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 108450 | 2026-07-05 11:59:01 |
| `data/processed/graficos_modelo79a/02_scatter_retorno_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 106085 | 2026-07-05 11:59:01 |
| `data/processed/graficos_modelo79a/02_scatter_retorno_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 94840 | 2026-07-05 11:59:02 |
| `data/processed/graficos_modelo79a/02_scatter_retorno_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 102163 | 2026-07-05 11:59:02 |
| `data/processed/graficos_monitor_amigable/seguimiento_actual_habitat.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 94058 | 2026-07-05 13:29:07 |
| `data/processed/graficos_monitor_amigable/seguimiento_actual_integra.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 99377 | 2026-07-05 13:29:07 |
| `data/processed/graficos_monitor_amigable/seguimiento_actual_prima.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 99315 | 2026-07-05 13:29:07 |
| `data/processed/graficos_monitor_amigable/seguimiento_actual_profuturo.png` | Mover a archivo |  | Grafico/resultado generado por modelos anteriores; no es codigo ni insumo canonico. | 105589 | 2026-07-05 13:29:08 |
| `data/processed/logs_modelo60/20260704_205937/01_validar_pronosticos_previos.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 9926 | 2026-07-04 20:59:38 |
| `data/processed/logs_modelo60/20260704_205937/02_generar_estimaciones_actuales.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 6879 | 2026-07-04 20:59:40 |
| `data/processed/logs_modelo60/20260704_205937/03_archivar_estimaciones_actuales.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 9929 | 2026-07-04 20:59:41 |
| `data/processed/logs_modelo60/20260704_205937/04_generar_panel_operativo.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 6003 | 2026-07-04 20:59:42 |
| `data/processed/logs_modelo60/20260704_224626/01_validar_pronosticos_previos.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 9926 | 2026-07-04 22:46:27 |
| `data/processed/logs_modelo60/20260704_224626/02_generar_estimaciones_actuales.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 6879 | 2026-07-04 22:46:29 |
| `data/processed/logs_modelo60/20260704_224626/03_archivar_estimaciones_actuales.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 9929 | 2026-07-04 22:46:30 |
| `data/processed/logs_modelo60/20260704_224626/04_generar_panel_operativo.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 6003 | 2026-07-04 22:46:31 |
| `data/processed/logs_modelo60/20260704_225110/01_validar_pronosticos_previos.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 10185 | 2026-07-04 22:51:11 |
| `data/processed/logs_modelo60/20260704_225110/02_generar_estimaciones_actuales.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 10153 | 2026-07-04 22:51:13 |
| `data/processed/logs_modelo60/20260704_225110/03_archivar_estimaciones_actuales.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 10182 | 2026-07-04 22:51:13 |
| `data/processed/logs_modelo60/20260704_225110/04_generar_panel_operativo.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 7774 | 2026-07-04 22:51:15 |
| `data/processed/mercados_catalogo_factores.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1199 | 2026-07-04 16:44:22 |
| `data/processed/mercados_control_cobertura.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2005 | 2026-07-04 16:44:22 |
| `data/processed/mercados_errores_descarga.csv` | Posible eliminar | Grupo 1 | Duplicado exacto de salida generada; validar antes de borrar si se usa como evidencia. | 5 | 2026-07-04 16:44:22 |
| `data/processed/mercados_factores_bloques_ortogonales.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 567165 | 2026-07-04 17:04:39 |
| `data/processed/mercados_factores_modelo.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1730132 | 2026-07-04 16:44:22 |
| `data/processed/mercados_precios_ajustados.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1471160 | 2026-07-04 16:44:21 |
| `data/processed/mercados_retornos_en_pen.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1612402 | 2026-07-04 16:44:22 |
| `data/processed/mercados_retornos_locales.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1617230 | 2026-07-04 16:44:22 |
| `data/processed/mercados_retornos_log_locales.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1617433 | 2026-07-04 16:44:22 |
| `data/processed/modelo_base_nowcast_coeficientes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 23441 | 2026-07-04 16:50:02 |
| `data/processed/modelo_base_nowcast_metricas.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 3320 | 2026-07-04 16:50:02 |
| `data/processed/modelo_base_nowcast_predicciones.csv` | Mover a archivo |  | Resultado experimental/validacion; conservar para trazabilidad, fuera del flujo operativo. | 430147 | 2026-07-04 16:50:02 |
| `data/processed/modelos_modelo64/habitat_ardl_ols.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 3069 | 2026-07-04 23:33:01 |
| `data/processed/modelos_modelo64/habitat_ardl_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2993 | 2026-07-04 23:33:23 |
| `data/processed/modelos_modelo64/habitat_elastic_net.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2169 | 2026-07-04 23:31:35 |
| `data/processed/modelos_modelo64/habitat_huber.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 4535 | 2026-07-04 23:32:25 |
| `data/processed/modelos_modelo64/habitat_lad_q50.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2033 | 2026-07-04 23:32:48 |
| `data/processed/modelos_modelo64/habitat_ols.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2059 | 2026-07-04 23:30:40 |
| `data/processed/modelos_modelo64/habitat_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2063 | 2026-07-04 23:31:01 |
| `data/processed/modelos_modelo64/integra_ardl_ols.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 3037 | 2026-07-04 23:36:46 |
| `data/processed/modelos_modelo64/integra_ardl_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2961 | 2026-07-04 23:37:08 |
| `data/processed/modelos_modelo64/integra_elastic_net.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2149 | 2026-07-04 23:34:53 |
| `data/processed/modelos_modelo64/integra_huber.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 4515 | 2026-07-04 23:36:11 |
| `data/processed/modelos_modelo64/integra_lad_q50.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2013 | 2026-07-04 23:36:34 |
| `data/processed/modelos_modelo64/integra_ols.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2039 | 2026-07-04 23:33:35 |
| `data/processed/modelos_modelo64/integra_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2043 | 2026-07-04 23:33:58 |
| `data/processed/modelos_modelo64/prima_ardl_ols.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 4011 | 2026-07-04 23:39:48 |
| `data/processed/modelos_modelo64/prima_ardl_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 3871 | 2026-07-04 23:40:13 |
| `data/processed/modelos_modelo64/prima_elastic_net.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2351 | 2026-07-04 23:38:19 |
| `data/processed/modelos_modelo64/prima_huber.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 4717 | 2026-07-04 23:39:11 |
| `data/processed/modelos_modelo64/prima_lad_q50.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2215 | 2026-07-04 23:39:35 |
| `data/processed/modelos_modelo64/prima_ols.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2257 | 2026-07-04 23:37:19 |
| `data/processed/modelos_modelo64/prima_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2245 | 2026-07-04 23:37:43 |
| `data/processed/modelos_modelo64/profuturo_ardl_ols.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 3039 | 2026-07-04 23:43:28 |
| `data/processed/modelos_modelo64/profuturo_ardl_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2963 | 2026-07-04 23:43:50 |
| `data/processed/modelos_modelo64/profuturo_elastic_net.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2151 | 2026-07-04 23:41:26 |
| `data/processed/modelos_modelo64/profuturo_huber.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 4517 | 2026-07-04 23:42:18 |
| `data/processed/modelos_modelo64/profuturo_lad_q50.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2015 | 2026-07-04 23:43:02 |
| `data/processed/modelos_modelo64/profuturo_ols.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2041 | 2026-07-04 23:40:26 |
| `data/processed/modelos_modelo64/profuturo_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2045 | 2026-07-04 23:40:50 |
| `data/processed/modelos_modelo66/habitat_diario_extra_trees.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 13150894 | 2026-07-05 00:34:15 |
| `data/processed/modelos_modelo66/habitat_diario_gradient_boosting.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 183016 | 2026-07-05 00:29:59 |
| `data/processed/modelos_modelo66/habitat_diario_poly_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 6008 | 2026-07-05 00:29:08 |
| `data/processed/modelos_modelo66/habitat_diario_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2891 | 2026-07-05 00:28:58 |
| `data/processed/modelos_modelo66/habitat_diario_svr_rbf.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 256792 | 2026-07-05 00:29:33 |
| `data/processed/modelos_modelo66/habitat_directo_extra_trees.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 3062070 | 2026-07-05 00:37:05 |
| `data/processed/modelos_modelo66/habitat_directo_gradient_boosting.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 188000 | 2026-07-05 00:37:02 |
| `data/processed/modelos_modelo66/habitat_directo_poly_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 12112 | 2026-07-05 00:36:36 |
| `data/processed/modelos_modelo66/habitat_directo_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 3811 | 2026-07-05 00:36:34 |
| `data/processed/modelos_modelo66/habitat_directo_svr_rbf.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 416864 | 2026-07-05 00:36:43 |
| `data/processed/modelos_modelo66/integra_diario_extra_trees.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2981426 | 2026-07-05 00:42:05 |
| `data/processed/modelos_modelo66/integra_diario_gradient_boosting.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 183692 | 2026-07-05 00:39:04 |
| `data/processed/modelos_modelo66/integra_diario_poly_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 6396 | 2026-07-05 00:37:36 |
| `data/processed/modelos_modelo66/integra_diario_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2831 | 2026-07-05 00:37:20 |
| `data/processed/modelos_modelo66/integra_diario_svr_rbf.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 258980 | 2026-07-05 00:38:21 |
| `data/processed/modelos_modelo66/integra_directo_extra_trees.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 757579 | 2026-07-05 00:43:50 |
| `data/processed/modelos_modelo66/integra_directo_gradient_boosting.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 124004 | 2026-07-05 00:43:49 |
| `data/processed/modelos_modelo66/integra_directo_poly_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 12068 | 2026-07-05 00:43:29 |
| `data/processed/modelos_modelo66/integra_directo_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 3751 | 2026-07-05 00:43:28 |
| `data/processed/modelos_modelo66/integra_directo_svr_rbf.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 417588 | 2026-07-05 00:43:36 |
| `data/processed/modelos_modelo66/prima_diario_extra_trees.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 3052628 | 2026-07-05 00:47:19 |
| `data/processed/modelos_modelo66/prima_diario_gradient_boosting.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 191966 | 2026-07-05 00:45:00 |
| `data/processed/modelos_modelo66/prima_diario_poly_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 16262 | 2026-07-05 00:44:09 |
| `data/processed/modelos_modelo66/prima_diario_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 3921 | 2026-07-05 00:43:59 |
| `data/processed/modelos_modelo66/prima_diario_svr_rbf.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 442509 | 2026-07-05 00:44:27 |
| `data/processed/modelos_modelo66/prima_directo_extra_trees.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 3163794 | 2026-07-05 00:49:19 |
| `data/processed/modelos_modelo66/prima_directo_gradient_boosting.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 124844 | 2026-07-05 00:49:18 |
| `data/processed/modelos_modelo66/prima_directo_poly_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 25444 | 2026-07-05 00:48:56 |
| `data/processed/modelos_modelo66/prima_directo_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 5039 | 2026-07-05 00:48:55 |
| `data/processed/modelos_modelo66/prima_directo_svr_rbf.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 616035 | 2026-07-05 00:49:00 |
| `data/processed/modelos_modelo66/profuturo_diario_extra_trees.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2990642 | 2026-07-05 00:52:45 |
| `data/processed/modelos_modelo66/profuturo_diario_gradient_boosting.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 186284 | 2026-07-05 00:50:27 |
| `data/processed/modelos_modelo66/profuturo_diario_poly_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 6412 | 2026-07-05 00:49:37 |
| `data/processed/modelos_modelo66/profuturo_diario_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 2831 | 2026-07-05 00:49:28 |
| `data/processed/modelos_modelo66/profuturo_diario_svr_rbf.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 256732 | 2026-07-05 00:50:02 |
| `data/processed/modelos_modelo66/profuturo_directo_extra_trees.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 746779 | 2026-07-05 00:54:30 |
| `data/processed/modelos_modelo66/profuturo_directo_gradient_boosting.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 124004 | 2026-07-05 00:54:29 |
| `data/processed/modelos_modelo66/profuturo_directo_poly_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 11364 | 2026-07-05 00:54:10 |
| `data/processed/modelos_modelo66/profuturo_directo_ridge.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 3751 | 2026-07-05 00:54:09 |
| `data/processed/modelos_modelo66/profuturo_directo_svr_rbf.joblib` | No tocar |  | Artefacto de modelo entrenado; conservar hasta definir version de produccion. | 415436 | 2026-07-05 00:54:17 |
| `data/processed/monitor_sbs_automatico.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 5337 | 2026-07-05 13:00:02 |
| `data/processed/nowcast_historico_estimaciones.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 3467 | 2026-07-04 16:55:09 |
| `data/processed/nowcast_operativo_fondo3.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 3076 | 2026-07-04 16:52:50 |
| `data/processed/nowcast_operativo_resumen_modelos.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 778 | 2026-07-04 16:52:50 |
| `data/processed/nowcast_validacion_detalle.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 4002 | 2026-07-04 16:55:09 |
| `data/processed/nowcast_validacion_resumen.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 150 | 2026-07-04 16:55:09 |
| `data/processed/pronostico_diario_automatico.log` | Mover a archivo |  | Log de ejecucion; util para auditoria, no para operacion diaria. | 6764 | 2026-07-05 12:55:20 |
| `data/processed/respaldos_scripts/cobertura_20260704_225030/57_generar_seguimiento_operativo_y_grafica_actual.py` | Mover a archivo |  | Respaldo historico de scripts; mantener archivado, fuera del src activo. | 31615 | 2026-07-04 20:42:55 |
| `data/processed/respaldos_scripts/cobertura_20260704_225030/58_archivar_y_validar_estimaciones_sbs.py` | Mover a archivo |  | Respaldo historico de scripts; mantener archivado, fuera del src activo. | 31077 | 2026-07-04 20:52:46 |
| `data/processed/respaldos_scripts/cobertura_20260704_225030/59_generar_panel_operativo_fondo3.py` | Mover a archivo |  | Respaldo historico de scripts; mantener archivado, fuera del src activo. | 28541 | 2026-07-04 20:55:42 |
| `data/processed/respaldos_scripts/cobertura_20260704_225030/60_orquestar_flujo_operativo_fondo3.py` | Mover a archivo |  | Respaldo historico de scripts; mantener archivado, fuera del src activo. | 10934 | 2026-07-04 20:59:13 |
| `data/processed/sbs_fondo3_anomalias_contexto.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 2528 | 2026-07-04 16:36:48 |
| `data/processed/sbs_fondo3_auditoria_resumen.csv` | Mantener |  | Salida procesada vigente o resumen operativo referenciado por monitores/modelos. | 376 | 2026-07-04 16:34:55 |
| `data/processed/sbs_fondo3_base_maestra.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 1763888 | 2026-07-04 16:34:55 |
| `data/processed/sbs_fondo3_base_maestra_ancha.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 169990 | 2026-07-04 16:34:55 |
| `data/processed/sbs_fondo3_clasificacion_anomalias.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 485 | 2026-07-04 16:38:52 |
| `data/processed/sbs_fondo3_comparacion_anomalias_por_afp.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 1863 | 2026-07-04 16:38:52 |
| `data/processed/sbs_fondo3_control_calidad.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 439 | 2026-07-04 16:32:17 |
| `data/processed/sbs_fondo3_diferencias_fuentes.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 241 | 2026-07-04 16:34:55 |
| `data/processed/sbs_fondo3_errores.csv` | Posible eliminar | Grupo 1 | Duplicado exacto de salida generada; validar antes de borrar si se usa como evidencia. | 5 | 2026-07-04 16:32:17 |
| `data/processed/sbs_fondo3_fechas_incompletas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 50 | 2026-07-04 16:34:55 |
| `data/processed/sbs_fondo3_historico_ancho.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 178631 | 2026-07-04 16:32:17 |
| `data/processed/sbs_fondo3_historico_largo.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 2915644 | 2026-07-04 16:32:17 |
| `data/processed/sbs_fondo3_variaciones_anomalas.csv` | Mover a archivo |  | Salida procesada no identificada como fuente primaria ni artefacto activo. | 238 | 2026-07-04 16:34:55 |
| `data/processed/sbs_fondo3_vintages.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 8301 | 2026-07-04 16:17:08 |
| `data/processed/vistas_historico/FP-1359-my2026_hoja_01_VC-Diario-Fondo0_vista.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 2069 | 2026-07-04 16:20:35 |
| `data/processed/vistas_historico/FP-1359-my2026_hoja_02_VC-Diario-Fondo1_vista.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 1830 | 2026-07-04 16:20:35 |
| `data/processed/vistas_historico/FP-1359-my2026_hoja_03_VC-Diario-Fondo2_vista.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 1866 | 2026-07-04 16:20:35 |
| `data/processed/vistas_historico/FP-1359-my2026_hoja_04_VC-Diario-Fondo3_vista.csv` | No tocar |  | Base historica/procesada clave para trazabilidad y backtesting. | 1808 | 2026-07-04 16:20:35 |
| `data/raw/mercados/ACWI.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 283208 | 2026-07-04 16:43:09 |
| `data/raw/mercados/COPX.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 282553 | 2026-07-04 16:43:56 |
| `data/raw/mercados/CPER.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 273651 | 2026-07-04 16:43:54 |
| `data/raw/mercados/DX_Y_NYB.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 281828 | 2026-07-04 16:44:16 |
| `data/raw/mercados/EEM.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 284590 | 2026-07-04 16:43:16 |
| `data/raw/mercados/EPU.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 278485 | 2026-07-04 16:43:20 |
| `data/raw/mercados/EWJ.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 280632 | 2026-07-04 16:43:28 |
| `data/raw/mercados/GLD.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 280855 | 2026-07-04 16:43:51 |
| `data/raw/mercados/HYG.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 281784 | 2026-07-04 16:44:05 |
| `data/raw/mercados/IDX_VIX.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 266998 | 2026-07-04 16:44:09 |
| `data/raw/mercados/ILF.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 284401 | 2026-07-04 16:43:18 |
| `data/raw/mercados/LQD.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 282756 | 2026-07-04 16:44:03 |
| `data/raw/mercados/MCHI.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 283069 | 2026-07-04 16:43:31 |
| `data/raw/mercados/PEN_X.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 281945 | 2026-07-04 16:44:20 |
| `data/raw/mercados/QQQ.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 285537 | 2026-07-04 16:43:14 |
| `data/raw/mercados/SPY.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 285780 | 2026-07-04 16:43:12 |
| `data/raw/mercados/TLT.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 282397 | 2026-07-04 16:44:00 |
| `data/raw/mercados/USO.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 274229 | 2026-07-04 16:43:57 |
| `data/raw/mercados/VGK.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 280373 | 2026-07-04 16:43:22 |
| `data/raw/mercados/XLB.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 285018 | 2026-07-04 16:43:41 |
| `data/raw/mercados/XLE.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 286773 | 2026-07-04 16:43:39 |
| `data/raw/mercados/XLF.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 287026 | 2026-07-04 16:43:37 |
| `data/raw/mercados/XLI.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 281867 | 2026-07-04 16:43:43 |
| `data/raw/mercados/XLK.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 285073 | 2026-07-04 16:43:35 |
| `data/raw/mercados/XLP.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 280986 | 2026-07-04 16:43:49 |
| `data/raw/mercados/XLV.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 283503 | 2026-07-04 16:43:45 |
| `data/raw/mercados/XLY.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 281389 | 2026-07-04 16:43:47 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ab2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 540033 | 2026-07-04 17:54:18 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ab2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 602500 | 2026-07-04 17:54:30 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ab2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1163264 | 2026-07-04 17:54:44 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ab2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1097728 | 2026-07-04 17:54:57 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ab2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1369600 | 2026-07-04 17:55:10 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ab2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 595593 | 2026-07-04 17:55:24 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ab2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 592539 | 2026-07-04 17:55:40 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ab2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1263104 | 2026-07-04 17:55:57 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ab2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1212928 | 2026-07-04 17:56:11 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ab2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 627290 | 2026-07-04 17:56:23 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ab2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 546706 | 2026-07-04 17:56:38 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ag2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 534489 | 2026-07-04 17:54:22 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ag2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 609933 | 2026-07-04 17:54:34 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ag2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1159680 | 2026-07-04 17:54:49 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ag2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1222656 | 2026-07-04 17:55:01 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ag2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1281024 | 2026-07-04 17:55:15 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ag2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 10086608 | 2026-07-04 17:55:31 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ag2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 594796 | 2026-07-04 17:55:48 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ag2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1240576 | 2026-07-04 17:56:02 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ag2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 555528 | 2026-07-04 17:56:15 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ag2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 617647 | 2026-07-04 17:56:29 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ag2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 547979 | 2026-07-04 17:56:42 |
| `data/raw/sbs/ca0001_composicion/CA-0001-di2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 559278 | 2026-07-04 17:54:26 |
| `data/raw/sbs/ca0001_composicion/CA-0001-di2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 617915 | 2026-07-04 17:54:38 |
| `data/raw/sbs/ca0001_composicion/CA-0001-di2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1284096 | 2026-07-04 17:54:53 |
| `data/raw/sbs/ca0001_composicion/CA-0001-di2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1222144 | 2026-07-04 17:55:06 |
| `data/raw/sbs/ca0001_composicion/CA-0001-di2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 625292 | 2026-07-04 17:55:19 |
| `data/raw/sbs/ca0001_composicion/CA-0001-di2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1241088 | 2026-07-04 17:55:35 |
| `data/raw/sbs/ca0001_composicion/CA-0001-di2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 582145 | 2026-07-04 17:55:53 |
| `data/raw/sbs/ca0001_composicion/CA-0001-di2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 575128 | 2026-07-04 17:56:06 |
| `data/raw/sbs/ca0001_composicion/CA-0001-di2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 595052 | 2026-07-04 17:56:19 |
| `data/raw/sbs/ca0001_composicion/CA-0001-di2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 621021 | 2026-07-04 17:56:34 |
| `data/raw/sbs/ca0001_composicion/CA-0001-di2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 558258 | 2026-07-04 17:38:38 |
| `data/raw/sbs/ca0001_composicion/CA-0001-en2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1001984 | 2026-07-04 17:54:15 |
| `data/raw/sbs/ca0001_composicion/CA-0001-en2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 553725 | 2026-07-04 17:54:27 |
| `data/raw/sbs/ca0001_composicion/CA-0001-en2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1125376 | 2026-07-04 17:54:40 |
| `data/raw/sbs/ca0001_composicion/CA-0001-en2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1180160 | 2026-07-04 17:54:54 |
| `data/raw/sbs/ca0001_composicion/CA-0001-en2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1224192 | 2026-07-04 17:55:07 |
| `data/raw/sbs/ca0001_composicion/CA-0001-en2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1275392 | 2026-07-04 17:55:21 |
| `data/raw/sbs/ca0001_composicion/CA-0001-en2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 584994 | 2026-07-04 17:55:36 |
| `data/raw/sbs/ca0001_composicion/CA-0001-en2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1230848 | 2026-07-04 17:55:54 |
| `data/raw/sbs/ca0001_composicion/CA-0001-en2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1254400 | 2026-07-04 17:56:08 |
| `data/raw/sbs/ca0001_composicion/CA-0001-en2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 623428 | 2026-07-04 17:56:20 |
| `data/raw/sbs/ca0001_composicion/CA-0001-en2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 593034 | 2026-07-04 17:56:35 |
| `data/raw/sbs/ca0001_composicion/CA-0001-en2026.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 546945 | 2026-07-04 17:38:36 |
| `data/raw/sbs/ca0001_composicion/CA-0001-fe2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 997888 | 2026-07-04 17:54:16 |
| `data/raw/sbs/ca0001_composicion/CA-0001-fe2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 591741 | 2026-07-04 17:54:28 |
| `data/raw/sbs/ca0001_composicion/CA-0001-fe2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1141248 | 2026-07-04 17:54:41 |
| `data/raw/sbs/ca0001_composicion/CA-0001-fe2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1196544 | 2026-07-04 17:54:55 |
| `data/raw/sbs/ca0001_composicion/CA-0001-fe2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1231872 | 2026-07-04 17:55:08 |
| `data/raw/sbs/ca0001_composicion/CA-0001-fe2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 603068 | 2026-07-04 17:55:22 |
| `data/raw/sbs/ca0001_composicion/CA-0001-fe2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 586009 | 2026-07-04 17:55:37 |
| `data/raw/sbs/ca0001_composicion/CA-0001-fe2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1251840 | 2026-07-04 17:55:55 |
| `data/raw/sbs/ca0001_composicion/CA-0001-fe2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1210880 | 2026-07-04 17:56:09 |
| `data/raw/sbs/ca0001_composicion/CA-0001-fe2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 616414 | 2026-07-04 17:56:21 |
| `data/raw/sbs/ca0001_composicion/CA-0001-fe2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 602784 | 2026-07-04 17:56:36 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jl2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 552059 | 2026-07-04 17:54:21 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jl2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 591262 | 2026-07-04 17:54:33 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jl2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1176576 | 2026-07-04 17:54:48 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jl2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1198592 | 2026-07-04 17:55:00 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jl2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 3660800 | 2026-07-04 17:55:14 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jl2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 10116759 | 2026-07-04 17:55:29 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jl2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 10093216 | 2026-07-04 17:55:47 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jl2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 578757 | 2026-07-04 17:56:01 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jl2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 555509 | 2026-07-04 17:56:14 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jl2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 634941 | 2026-07-04 17:56:28 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jl2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 544741 | 2026-07-04 17:56:41 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jn2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 536488 | 2026-07-04 17:54:20 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jn2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 584959 | 2026-07-04 17:54:32 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jn2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1182208 | 2026-07-04 17:54:46 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jn2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1211392 | 2026-07-04 17:54:59 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jn2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1238016 | 2026-07-04 17:55:12 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jn2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1349120 | 2026-07-04 17:55:26 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jn2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1352192 | 2026-07-04 17:55:45 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jn2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1254912 | 2026-07-04 17:56:00 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jn2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 555983 | 2026-07-04 17:56:13 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jn2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 627402 | 2026-07-04 17:56:27 |
| `data/raw/sbs/ca0001_composicion/CA-0001-jn2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 553389 | 2026-07-04 17:56:40 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ma2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 543914 | 2026-07-04 17:54:17 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ma2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 545776 | 2026-07-04 17:54:29 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ma2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1172480 | 2026-07-04 17:54:43 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ma2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1199104 | 2026-07-04 17:54:56 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ma2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1231360 | 2026-07-04 17:55:09 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ma2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 599245 | 2026-07-04 17:55:23 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ma2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 3660800 | 2026-07-04 17:55:39 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ma2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 585042 | 2026-07-04 17:55:56 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ma2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1218560 | 2026-07-04 17:56:10 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ma2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 617084 | 2026-07-04 17:56:22 |
| `data/raw/sbs/ca0001_composicion/CA-0001-ma2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 580952 | 2026-07-04 17:56:37 |
| `data/raw/sbs/ca0001_composicion/CA-0001-my2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 534055 | 2026-07-04 17:54:19 |
| `data/raw/sbs/ca0001_composicion/CA-0001-my2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 586515 | 2026-07-04 17:54:31 |
| `data/raw/sbs/ca0001_composicion/CA-0001-my2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1178624 | 2026-07-04 17:54:45 |
| `data/raw/sbs/ca0001_composicion/CA-0001-my2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1108480 | 2026-07-04 17:54:58 |
| `data/raw/sbs/ca0001_composicion/CA-0001-my2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1252352 | 2026-07-04 17:55:11 |
| `data/raw/sbs/ca0001_composicion/CA-0001-my2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 594604 | 2026-07-04 17:55:25 |
| `data/raw/sbs/ca0001_composicion/CA-0001-my2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 10073679 | 2026-07-04 17:55:44 |
| `data/raw/sbs/ca0001_composicion/CA-0001-my2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1286656 | 2026-07-04 17:55:59 |
| `data/raw/sbs/ca0001_composicion/CA-0001-my2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 560139 | 2026-07-04 17:56:12 |
| `data/raw/sbs/ca0001_composicion/CA-0001-my2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 627287 | 2026-07-04 17:56:25 |
| `data/raw/sbs/ca0001_composicion/CA-0001-my2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 541012 | 2026-07-04 17:56:39 |
| `data/raw/sbs/ca0001_composicion/CA-0001-no2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 562014 | 2026-07-04 17:54:25 |
| `data/raw/sbs/ca0001_composicion/CA-0001-no2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1134080 | 2026-07-04 17:54:37 |
| `data/raw/sbs/ca0001_composicion/CA-0001-no2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1192448 | 2026-07-04 17:54:52 |
| `data/raw/sbs/ca0001_composicion/CA-0001-no2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 3724288 | 2026-07-04 17:55:05 |
| `data/raw/sbs/ca0001_composicion/CA-0001-no2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 617561 | 2026-07-04 17:55:18 |
| `data/raw/sbs/ca0001_composicion/CA-0001-no2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 581755 | 2026-07-04 17:55:34 |
| `data/raw/sbs/ca0001_composicion/CA-0001-no2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1231872 | 2026-07-04 17:55:52 |
| `data/raw/sbs/ca0001_composicion/CA-0001-no2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 570036 | 2026-07-04 17:56:05 |
| `data/raw/sbs/ca0001_composicion/CA-0001-no2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 575827 | 2026-07-04 17:56:18 |
| `data/raw/sbs/ca0001_composicion/CA-0001-no2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 607301 | 2026-07-04 17:56:32 |
| `data/raw/sbs/ca0001_composicion/CA-0001-no2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 549638 | 2026-07-04 17:38:39 |
| `data/raw/sbs/ca0001_composicion/CA-0001-oc2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 575889 | 2026-07-04 17:54:24 |
| `data/raw/sbs/ca0001_composicion/CA-0001-oc2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 620488 | 2026-07-04 17:54:36 |
| `data/raw/sbs/ca0001_composicion/CA-0001-oc2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1249792 | 2026-07-04 17:54:51 |
| `data/raw/sbs/ca0001_composicion/CA-0001-oc2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1227264 | 2026-07-04 17:55:03 |
| `data/raw/sbs/ca0001_composicion/CA-0001-oc2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1287680 | 2026-07-04 17:55:17 |
| `data/raw/sbs/ca0001_composicion/CA-0001-oc2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1241600 | 2026-07-04 17:55:33 |
| `data/raw/sbs/ca0001_composicion/CA-0001-oc2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1251840 | 2026-07-04 17:55:50 |
| `data/raw/sbs/ca0001_composicion/CA-0001-oc2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1220608 | 2026-07-04 17:56:04 |
| `data/raw/sbs/ca0001_composicion/CA-0001-oc2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 621582 | 2026-07-04 17:56:17 |
| `data/raw/sbs/ca0001_composicion/CA-0001-oc2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 604736 | 2026-07-04 17:56:31 |
| `data/raw/sbs/ca0001_composicion/CA-0001-oc2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 549135 | 2026-07-04 17:56:44 |
| `data/raw/sbs/ca0001_composicion/CA-0001-se2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 649604 | 2026-07-04 17:54:23 |
| `data/raw/sbs/ca0001_composicion/CA-0001-se2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 605394 | 2026-07-04 17:54:35 |
| `data/raw/sbs/ca0001_composicion/CA-0001-se2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1197056 | 2026-07-04 17:54:50 |
| `data/raw/sbs/ca0001_composicion/CA-0001-se2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1392128 | 2026-07-04 17:55:02 |
| `data/raw/sbs/ca0001_composicion/CA-0001-se2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 1261568 | 2026-07-04 17:55:16 |
| `data/raw/sbs/ca0001_composicion/CA-0001-se2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 595712 | 2026-07-04 17:55:32 |
| `data/raw/sbs/ca0001_composicion/CA-0001-se2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 589568 | 2026-07-04 17:55:49 |
| `data/raw/sbs/ca0001_composicion/CA-0001-se2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 568663 | 2026-07-04 17:56:03 |
| `data/raw/sbs/ca0001_composicion/CA-0001-se2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 562287 | 2026-07-04 17:56:16 |
| `data/raw/sbs/ca0001_composicion/CA-0001-se2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 615165 | 2026-07-04 17:56:30 |
| `data/raw/sbs/ca0001_composicion/CA-0001-se2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 545397 | 2026-07-04 17:56:43 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ab2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 182784 | 2026-07-04 17:19:33 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ab2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 199168 | 2026-07-04 17:19:34 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ab2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 186880 | 2026-07-04 17:19:36 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ab2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 246784 | 2026-07-04 17:19:38 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ab2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 188416 | 2026-07-04 17:19:40 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ab2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 217088 | 2026-07-04 17:19:41 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ab2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 186880 | 2026-07-04 17:19:43 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ab2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 171008 | 2026-07-04 17:19:45 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ab2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 172032 | 2026-07-04 17:19:47 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ab2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 184832 | 2026-07-04 17:19:48 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ab2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 162816 | 2026-07-04 17:19:50 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ab2026.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 162304 | 2026-07-04 17:12:50 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ag2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 631808 | 2026-07-04 17:19:33 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ag2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 282624 | 2026-07-04 17:19:35 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ag2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 192512 | 2026-07-04 17:19:37 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ag2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 245248 | 2026-07-04 17:19:38 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ag2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 279040 | 2026-07-04 17:19:40 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ag2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 184832 | 2026-07-04 17:19:42 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ag2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 179712 | 2026-07-04 17:19:44 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ag2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 179712 | 2026-07-04 17:19:45 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ag2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 180736 | 2026-07-04 17:19:47 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ag2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 162304 | 2026-07-04 17:19:49 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ag2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 153600 | 2026-07-04 17:19:50 |
| `data/raw/sbs/fp1356_cartera/FP-1356-di2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 179712 | 2026-07-04 17:19:34 |
| `data/raw/sbs/fp1356_cartera/FP-1356-di2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 252416 | 2026-07-04 17:19:36 |
| `data/raw/sbs/fp1356_cartera/FP-1356-di2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 274432 | 2026-07-04 17:19:37 |
| `data/raw/sbs/fp1356_cartera/FP-1356-di2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 246272 | 2026-07-04 17:19:39 |
| `data/raw/sbs/fp1356_cartera/FP-1356-di2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 223232 | 2026-07-04 17:19:41 |
| `data/raw/sbs/fp1356_cartera/FP-1356-di2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 188416 | 2026-07-04 17:19:42 |
| `data/raw/sbs/fp1356_cartera/FP-1356-di2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 180224 | 2026-07-04 17:19:44 |
| `data/raw/sbs/fp1356_cartera/FP-1356-di2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 171520 | 2026-07-04 17:19:46 |
| `data/raw/sbs/fp1356_cartera/FP-1356-di2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 180224 | 2026-07-04 17:19:48 |
| `data/raw/sbs/fp1356_cartera/FP-1356-di2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 162304 | 2026-07-04 17:19:49 |
| `data/raw/sbs/fp1356_cartera/FP-1356-di2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 153600 | 2026-07-04 17:19:51 |
| `data/raw/sbs/fp1356_cartera/FP-1356-en2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 194048 | 2026-07-04 17:19:32 |
| `data/raw/sbs/fp1356_cartera/FP-1356-en2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 176128 | 2026-07-04 17:19:34 |
| `data/raw/sbs/fp1356_cartera/FP-1356-en2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 186368 | 2026-07-04 17:19:36 |
| `data/raw/sbs/fp1356_cartera/FP-1356-en2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 213504 | 2026-07-04 17:19:37 |
| `data/raw/sbs/fp1356_cartera/FP-1356-en2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 256000 | 2026-07-04 17:19:39 |
| `data/raw/sbs/fp1356_cartera/FP-1356-en2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 192000 | 2026-07-04 17:19:41 |
| `data/raw/sbs/fp1356_cartera/FP-1356-en2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 178688 | 2026-07-04 17:19:43 |
| `data/raw/sbs/fp1356_cartera/FP-1356-en2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 180224 | 2026-07-04 17:19:44 |
| `data/raw/sbs/fp1356_cartera/FP-1356-en2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 170496 | 2026-07-04 17:19:46 |
| `data/raw/sbs/fp1356_cartera/FP-1356-en2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 180224 | 2026-07-04 17:19:48 |
| `data/raw/sbs/fp1356_cartera/FP-1356-en2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 162816 | 2026-07-04 17:19:49 |
| `data/raw/sbs/fp1356_cartera/FP-1356-en2026.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 162304 | 2026-07-04 17:19:51 |
| `data/raw/sbs/fp1356_cartera/FP-1356-fe2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 194048 | 2026-07-04 17:19:32 |
| `data/raw/sbs/fp1356_cartera/FP-1356-fe2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 176128 | 2026-07-04 17:19:34 |
| `data/raw/sbs/fp1356_cartera/FP-1356-fe2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 248832 | 2026-07-04 17:19:36 |
| `data/raw/sbs/fp1356_cartera/FP-1356-fe2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 182272 | 2026-07-04 17:19:37 |
| `data/raw/sbs/fp1356_cartera/FP-1356-fe2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 250368 | 2026-07-04 17:19:39 |
| `data/raw/sbs/fp1356_cartera/FP-1356-fe2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 216576 | 2026-07-04 17:19:41 |
| `data/raw/sbs/fp1356_cartera/FP-1356-fe2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 183296 | 2026-07-04 17:19:43 |
| `data/raw/sbs/fp1356_cartera/FP-1356-fe2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 179712 | 2026-07-04 17:19:44 |
| `data/raw/sbs/fp1356_cartera/FP-1356-fe2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 170496 | 2026-07-04 17:19:46 |
| `data/raw/sbs/fp1356_cartera/FP-1356-fe2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 180224 | 2026-07-04 17:19:48 |
| `data/raw/sbs/fp1356_cartera/FP-1356-fe2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 162304 | 2026-07-04 17:19:49 |
| `data/raw/sbs/fp1356_cartera/FP-1356-fe2026.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 161792 | 2026-07-04 17:19:51 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jl2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 631808 | 2026-07-04 17:19:33 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jl2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 282112 | 2026-07-04 17:19:35 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jl2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 185344 | 2026-07-04 17:19:37 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jl2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 113831 | 2026-07-04 17:19:38 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jl2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 271872 | 2026-07-04 17:19:40 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jl2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 176128 | 2026-07-04 17:19:42 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jl2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 187392 | 2026-07-04 17:19:43 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jl2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 179712 | 2026-07-04 17:19:45 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jl2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 180736 | 2026-07-04 17:19:47 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jl2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 162304 | 2026-07-04 17:19:48 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jl2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 159232 | 2026-07-04 17:19:50 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jn2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 182784 | 2026-07-04 17:19:33 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jn2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 196608 | 2026-07-04 17:19:35 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jn2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 188416 | 2026-07-04 17:19:36 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jn2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 250368 | 2026-07-04 17:19:38 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jn2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 256000 | 2026-07-04 17:19:40 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jn2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 184832 | 2026-07-04 17:19:42 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jn2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 187392 | 2026-07-04 17:19:43 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jn2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 171008 | 2026-07-04 17:19:45 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jn2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 172544 | 2026-07-04 17:19:47 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jn2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 151040 | 2026-07-04 17:19:48 |
| `data/raw/sbs/fp1356_cartera/FP-1356-jn2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 162816 | 2026-07-04 17:19:50 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ma2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 182272 | 2026-07-04 17:19:32 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ma2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 176640 | 2026-07-04 17:19:34 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ma2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 182784 | 2026-07-04 17:19:36 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ma2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 248832 | 2026-07-04 17:19:38 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ma2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 257024 | 2026-07-04 17:19:39 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ma2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 216576 | 2026-07-04 17:19:41 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ma2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 183808 | 2026-07-04 17:19:43 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ma2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 172544 | 2026-07-04 17:19:44 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ma2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 171520 | 2026-07-04 17:19:47 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ma2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 180224 | 2026-07-04 17:19:48 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ma2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 162816 | 2026-07-04 17:19:50 |
| `data/raw/sbs/fp1356_cartera/FP-1356-ma2026.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 161792 | 2026-07-04 17:12:49 |
| `data/raw/sbs/fp1356_cartera/FP-1356-my2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 182784 | 2026-07-04 17:19:33 |
| `data/raw/sbs/fp1356_cartera/FP-1356-my2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 197120 | 2026-07-04 17:19:35 |
| `data/raw/sbs/fp1356_cartera/FP-1356-my2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 183808 | 2026-07-04 17:19:36 |
| `data/raw/sbs/fp1356_cartera/FP-1356-my2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 183808 | 2026-07-04 17:19:38 |
| `data/raw/sbs/fp1356_cartera/FP-1356-my2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 189952 | 2026-07-04 17:19:40 |
| `data/raw/sbs/fp1356_cartera/FP-1356-my2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 176128 | 2026-07-04 17:19:42 |
| `data/raw/sbs/fp1356_cartera/FP-1356-my2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 178176 | 2026-07-04 17:19:43 |
| `data/raw/sbs/fp1356_cartera/FP-1356-my2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 171008 | 2026-07-04 17:19:45 |
| `data/raw/sbs/fp1356_cartera/FP-1356-my2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 180736 | 2026-07-04 17:19:47 |
| `data/raw/sbs/fp1356_cartera/FP-1356-my2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 181248 | 2026-07-04 17:19:48 |
| `data/raw/sbs/fp1356_cartera/FP-1356-my2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 162304 | 2026-07-04 17:19:50 |
| `data/raw/sbs/fp1356_cartera/FP-1356-my2026.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 162304 | 2026-07-04 17:12:50 |
| `data/raw/sbs/fp1356_cartera/FP-1356-no2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 179200 | 2026-07-04 17:19:34 |
| `data/raw/sbs/fp1356_cartera/FP-1356-no2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 198144 | 2026-07-04 17:19:35 |
| `data/raw/sbs/fp1356_cartera/FP-1356-no2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 195584 | 2026-07-04 17:19:37 |
| `data/raw/sbs/fp1356_cartera/FP-1356-no2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 114582 | 2026-07-04 17:19:39 |
| `data/raw/sbs/fp1356_cartera/FP-1356-no2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 223744 | 2026-07-04 17:19:41 |
| `data/raw/sbs/fp1356_cartera/FP-1356-no2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 185344 | 2026-07-04 17:19:42 |
| `data/raw/sbs/fp1356_cartera/FP-1356-no2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 187392 | 2026-07-04 17:19:44 |
| `data/raw/sbs/fp1356_cartera/FP-1356-no2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 171008 | 2026-07-04 17:19:46 |
| `data/raw/sbs/fp1356_cartera/FP-1356-no2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 172032 | 2026-07-04 17:19:47 |
| `data/raw/sbs/fp1356_cartera/FP-1356-no2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 161792 | 2026-07-04 17:19:49 |
| `data/raw/sbs/fp1356_cartera/FP-1356-no2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 153600 | 2026-07-04 17:19:51 |
| `data/raw/sbs/fp1356_cartera/FP-1356-oc2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 177664 | 2026-07-04 17:19:34 |
| `data/raw/sbs/fp1356_cartera/FP-1356-oc2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 200192 | 2026-07-04 17:19:35 |
| `data/raw/sbs/fp1356_cartera/FP-1356-oc2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 256512 | 2026-07-04 17:19:37 |
| `data/raw/sbs/fp1356_cartera/FP-1356-oc2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 247296 | 2026-07-04 17:19:39 |
| `data/raw/sbs/fp1356_cartera/FP-1356-oc2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 223744 | 2026-07-04 17:19:40 |
| `data/raw/sbs/fp1356_cartera/FP-1356-oc2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 177152 | 2026-07-04 17:19:42 |
| `data/raw/sbs/fp1356_cartera/FP-1356-oc2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 175104 | 2026-07-04 17:19:44 |
| `data/raw/sbs/fp1356_cartera/FP-1356-oc2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 169984 | 2026-07-04 17:19:46 |
| `data/raw/sbs/fp1356_cartera/FP-1356-oc2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 181248 | 2026-07-04 17:19:47 |
| `data/raw/sbs/fp1356_cartera/FP-1356-oc2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 161792 | 2026-07-04 17:19:49 |
| `data/raw/sbs/fp1356_cartera/FP-1356-oc2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 153600 | 2026-07-04 17:19:51 |
| `data/raw/sbs/fp1356_cartera/FP-1356-se2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 176128 | 2026-07-04 17:19:33 |
| `data/raw/sbs/fp1356_cartera/FP-1356-se2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 295936 | 2026-07-04 17:19:35 |
| `data/raw/sbs/fp1356_cartera/FP-1356-se2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 193024 | 2026-07-04 17:19:37 |
| `data/raw/sbs/fp1356_cartera/FP-1356-se2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 238080 | 2026-07-04 17:19:39 |
| `data/raw/sbs/fp1356_cartera/FP-1356-se2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 320000 | 2026-07-04 17:19:40 |
| `data/raw/sbs/fp1356_cartera/FP-1356-se2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 177664 | 2026-07-04 17:19:42 |
| `data/raw/sbs/fp1356_cartera/FP-1356-se2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 187904 | 2026-07-04 17:19:44 |
| `data/raw/sbs/fp1356_cartera/FP-1356-se2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 179712 | 2026-07-04 17:19:46 |
| `data/raw/sbs/fp1356_cartera/FP-1356-se2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 180224 | 2026-07-04 17:19:47 |
| `data/raw/sbs/fp1356_cartera/FP-1356-se2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 163840 | 2026-07-04 17:19:49 |
| `data/raw/sbs/fp1356_cartera/FP-1356-se2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 153600 | 2026-07-04 17:19:50 |
| `data/raw/sbs/historico/FP-1359-ab2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 138752 | 2026-07-04 16:26:32 |
| `data/raw/sbs/historico/FP-1359-ab2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 143360 | 2026-07-04 16:26:37 |
| `data/raw/sbs/historico/FP-1359-ab2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 134144 | 2026-07-04 16:26:43 |
| `data/raw/sbs/historico/FP-1359-ab2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 192000 | 2026-07-04 16:26:48 |
| `data/raw/sbs/historico/FP-1359-ab2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 124928 | 2026-07-04 16:26:53 |
| `data/raw/sbs/historico/FP-1359-ab2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 152064 | 2026-07-04 16:26:59 |
| `data/raw/sbs/historico/FP-1359-ab2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 111616 | 2026-07-04 16:27:04 |
| `data/raw/sbs/historico/FP-1359-ab2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 111616 | 2026-07-04 16:27:10 |
| `data/raw/sbs/historico/FP-1359-ab2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 88576 | 2026-07-04 16:27:15 |
| `data/raw/sbs/historico/FP-1359-ab2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 96256 | 2026-07-04 16:27:20 |
| `data/raw/sbs/historico/FP-1359-ab2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 84992 | 2026-07-04 16:27:25 |
| `data/raw/sbs/historico/FP-1359-ab2026.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 93184 | 2026-07-04 16:27:30 |
| `data/raw/sbs/historico/FP-1359-ag2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 585728 | 2026-07-04 16:26:34 |
| `data/raw/sbs/historico/FP-1359-ag2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 197120 | 2026-07-04 16:26:39 |
| `data/raw/sbs/historico/FP-1359-ag2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 139776 | 2026-07-04 16:26:45 |
| `data/raw/sbs/historico/FP-1359-ag2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 188416 | 2026-07-04 16:26:49 |
| `data/raw/sbs/historico/FP-1359-ag2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 220672 | 2026-07-04 16:26:55 |
| `data/raw/sbs/historico/FP-1359-ag2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 111616 | 2026-07-04 16:27:01 |
| `data/raw/sbs/historico/FP-1359-ag2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 111616 | 2026-07-04 16:27:06 |
| `data/raw/sbs/historico/FP-1359-ag2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 112640 | 2026-07-04 16:27:11 |
| `data/raw/sbs/historico/FP-1359-ag2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 96768 | 2026-07-04 16:27:16 |
| `data/raw/sbs/historico/FP-1359-ag2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 95232 | 2026-07-04 16:27:22 |
| `data/raw/sbs/historico/FP-1359-ag2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 86528 | 2026-07-04 16:27:26 |
| `data/raw/sbs/historico/FP-1359-di2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 141824 | 2026-07-04 16:26:36 |
| `data/raw/sbs/historico/FP-1359-di2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 115712 | 2026-07-04 16:26:41 |
| `data/raw/sbs/historico/FP-1359-di2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 144896 | 2026-07-04 16:26:46 |
| `data/raw/sbs/historico/FP-1359-di2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 187904 | 2026-07-04 16:26:51 |
| `data/raw/sbs/historico/FP-1359-di2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 160256 | 2026-07-04 16:26:57 |
| `data/raw/sbs/historico/FP-1359-di2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 119296 | 2026-07-04 16:27:02 |
| `data/raw/sbs/historico/FP-1359-di2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 30552 | 2026-07-04 16:27:08 |
| `data/raw/sbs/historico/FP-1359-di2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 113152 | 2026-07-04 16:27:13 |
| `data/raw/sbs/historico/FP-1359-di2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 88064 | 2026-07-04 16:27:18 |
| `data/raw/sbs/historico/FP-1359-di2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 87552 | 2026-07-04 16:27:23 |
| `data/raw/sbs/historico/FP-1359-di2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 86016 | 2026-07-04 16:27:28 |
| `data/raw/sbs/historico/FP-1359-en2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 138240 | 2026-07-04 16:26:31 |
| `data/raw/sbs/historico/FP-1359-en2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 138752 | 2026-07-04 16:26:36 |
| `data/raw/sbs/historico/FP-1359-en2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 135168 | 2026-07-04 16:26:41 |
| `data/raw/sbs/historico/FP-1359-en2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 143872 | 2026-07-04 16:26:47 |
| `data/raw/sbs/historico/FP-1359-en2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 124928 | 2026-07-04 16:26:52 |
| `data/raw/sbs/historico/FP-1359-en2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 129024 | 2026-07-04 16:26:57 |
| `data/raw/sbs/historico/FP-1359-en2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 110592 | 2026-07-04 16:27:03 |
| `data/raw/sbs/historico/FP-1359-en2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 111104 | 2026-07-04 16:27:08 |
| `data/raw/sbs/historico/FP-1359-en2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 89088 | 2026-07-04 16:27:13 |
| `data/raw/sbs/historico/FP-1359-en2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 89088 | 2026-07-04 16:27:19 |
| `data/raw/sbs/historico/FP-1359-en2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 88576 | 2026-07-04 16:27:24 |
| `data/raw/sbs/historico/FP-1359-en2026.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 86016 | 2026-07-04 16:27:29 |
| `data/raw/sbs/historico/FP-1359-fe2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 137728 | 2026-07-04 16:26:31 |
| `data/raw/sbs/historico/FP-1359-fe2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 138752 | 2026-07-04 16:26:36 |
| `data/raw/sbs/historico/FP-1359-fe2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 228352 | 2026-07-04 16:26:41 |
| `data/raw/sbs/historico/FP-1359-fe2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 177152 | 2026-07-04 16:26:47 |
| `data/raw/sbs/historico/FP-1359-fe2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 71692 | 2026-07-04 16:26:52 |
| `data/raw/sbs/historico/FP-1359-fe2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 144384 | 2026-07-04 16:26:58 |
| `data/raw/sbs/historico/FP-1359-fe2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 111104 | 2026-07-04 16:27:03 |
| `data/raw/sbs/historico/FP-1359-fe2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 110592 | 2026-07-04 16:27:09 |
| `data/raw/sbs/historico/FP-1359-fe2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 88064 | 2026-07-04 16:27:14 |
| `data/raw/sbs/historico/FP-1359-fe2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 88064 | 2026-07-04 16:27:19 |
| `data/raw/sbs/historico/FP-1359-fe2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 92160 | 2026-07-04 16:27:24 |
| `data/raw/sbs/historico/FP-1359-fe2026.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 85504 | 2026-07-04 16:27:29 |
| `data/raw/sbs/historico/FP-1359-jl2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 586240 | 2026-07-04 16:26:33 |
| `data/raw/sbs/historico/FP-1359-jl2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 203776 | 2026-07-04 16:26:38 |
| `data/raw/sbs/historico/FP-1359-jl2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 134656 | 2026-07-04 16:26:44 |
| `data/raw/sbs/historico/FP-1359-jl2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 192000 | 2026-07-04 16:26:49 |
| `data/raw/sbs/historico/FP-1359-jl2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 220160 | 2026-07-04 16:26:54 |
| `data/raw/sbs/historico/FP-1359-jl2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 112640 | 2026-07-04 16:27:00 |
| `data/raw/sbs/historico/FP-1359-jl2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 111616 | 2026-07-04 16:27:05 |
| `data/raw/sbs/historico/FP-1359-jl2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 112128 | 2026-07-04 16:27:11 |
| `data/raw/sbs/historico/FP-1359-jl2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 88576 | 2026-07-04 16:27:16 |
| `data/raw/sbs/historico/FP-1359-jl2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 88576 | 2026-07-04 16:27:21 |
| `data/raw/sbs/historico/FP-1359-jl2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 84480 | 2026-07-04 16:27:26 |
| `data/raw/sbs/historico/FP-1359-jn2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 139264 | 2026-07-04 16:26:33 |
| `data/raw/sbs/historico/FP-1359-jn2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 143360 | 2026-07-04 16:26:38 |
| `data/raw/sbs/historico/FP-1359-jn2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 135168 | 2026-07-04 16:26:44 |
| `data/raw/sbs/historico/FP-1359-jn2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 124928 | 2026-07-04 16:26:49 |
| `data/raw/sbs/historico/FP-1359-jn2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 124416 | 2026-07-04 16:26:54 |
| `data/raw/sbs/historico/FP-1359-jn2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 112640 | 2026-07-04 16:27:00 |
| `data/raw/sbs/historico/FP-1359-jn2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 120832 | 2026-07-04 16:27:05 |
| `data/raw/sbs/historico/FP-1359-jn2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 112128 | 2026-07-04 16:27:10 |
| `data/raw/sbs/historico/FP-1359-jn2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 96768 | 2026-07-04 16:27:16 |
| `data/raw/sbs/historico/FP-1359-jn2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 92160 | 2026-07-04 16:27:21 |
| `data/raw/sbs/historico/FP-1359-jn2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 84480 | 2026-07-04 16:27:26 |
| `data/raw/sbs/historico/FP-1359-ma2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 139264 | 2026-07-04 16:26:32 |
| `data/raw/sbs/historico/FP-1359-ma2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 140288 | 2026-07-04 16:26:37 |
| `data/raw/sbs/historico/FP-1359-ma2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 102912 | 2026-07-04 16:26:42 |
| `data/raw/sbs/historico/FP-1359-ma2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 74311 | 2026-07-04 16:26:47 |
| `data/raw/sbs/historico/FP-1359-ma2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 74135 | 2026-07-04 16:26:53 |
| `data/raw/sbs/historico/FP-1359-ma2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 154112 | 2026-07-04 16:26:58 |
| `data/raw/sbs/historico/FP-1359-ma2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 31277 | 2026-07-04 16:27:04 |
| `data/raw/sbs/historico/FP-1359-ma2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 113152 | 2026-07-04 16:27:09 |
| `data/raw/sbs/historico/FP-1359-ma2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 89088 | 2026-07-04 16:27:14 |
| `data/raw/sbs/historico/FP-1359-ma2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 88064 | 2026-07-04 16:27:19 |
| `data/raw/sbs/historico/FP-1359-ma2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 84480 | 2026-07-04 16:27:24 |
| `data/raw/sbs/historico/FP-1359-ma2026.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 93184 | 2026-07-04 16:27:29 |
| `data/raw/sbs/historico/FP-1359-my2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 138240 | 2026-07-04 16:26:32 |
| `data/raw/sbs/historico/FP-1359-my2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 142848 | 2026-07-04 16:26:38 |
| `data/raw/sbs/historico/FP-1359-my2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 136192 | 2026-07-04 16:26:43 |
| `data/raw/sbs/historico/FP-1359-my2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 74867 | 2026-07-04 16:26:48 |
| `data/raw/sbs/historico/FP-1359-my2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 193024 | 2026-07-04 16:26:54 |
| `data/raw/sbs/historico/FP-1359-my2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 112640 | 2026-07-04 16:26:59 |
| `data/raw/sbs/historico/FP-1359-my2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 111104 | 2026-07-04 16:27:04 |
| `data/raw/sbs/historico/FP-1359-my2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 112128 | 2026-07-04 16:27:10 |
| `data/raw/sbs/historico/FP-1359-my2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 96768 | 2026-07-04 16:27:15 |
| `data/raw/sbs/historico/FP-1359-my2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 96768 | 2026-07-04 16:27:20 |
| `data/raw/sbs/historico/FP-1359-my2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 83968 | 2026-07-04 16:27:25 |
| `data/raw/sbs/historico/FP-1359-my2026.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 85504 | 2026-07-04 16:20:35 |
| `data/raw/sbs/historico/FP-1359-no2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 141824 | 2026-07-04 16:26:35 |
| `data/raw/sbs/historico/FP-1359-no2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 143872 | 2026-07-04 16:26:40 |
| `data/raw/sbs/historico/FP-1359-no2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 145920 | 2026-07-04 16:26:46 |
| `data/raw/sbs/historico/FP-1359-no2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 124928 | 2026-07-04 16:26:51 |
| `data/raw/sbs/historico/FP-1359-no2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 160256 | 2026-07-04 16:26:56 |
| `data/raw/sbs/historico/FP-1359-no2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 112640 | 2026-07-04 16:27:02 |
| `data/raw/sbs/historico/FP-1359-no2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 111616 | 2026-07-04 16:27:07 |
| `data/raw/sbs/historico/FP-1359-no2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 113152 | 2026-07-04 16:27:12 |
| `data/raw/sbs/historico/FP-1359-no2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 96768 | 2026-07-04 16:27:18 |
| `data/raw/sbs/historico/FP-1359-no2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 88576 | 2026-07-04 16:27:23 |
| `data/raw/sbs/historico/FP-1359-no2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 86016 | 2026-07-04 16:27:27 |
| `data/raw/sbs/historico/FP-1359-oc2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 138752 | 2026-07-04 16:26:35 |
| `data/raw/sbs/historico/FP-1359-oc2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 205312 | 2026-07-04 16:26:40 |
| `data/raw/sbs/historico/FP-1359-oc2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 201728 | 2026-07-04 16:26:45 |
| `data/raw/sbs/historico/FP-1359-oc2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 190976 | 2026-07-04 16:26:51 |
| `data/raw/sbs/historico/FP-1359-oc2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 160768 | 2026-07-04 16:26:56 |
| `data/raw/sbs/historico/FP-1359-oc2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 108544 | 2026-07-04 16:27:01 |
| `data/raw/sbs/historico/FP-1359-oc2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 104448 | 2026-07-04 16:27:07 |
| `data/raw/sbs/historico/FP-1359-oc2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 112128 | 2026-07-04 16:27:12 |
| `data/raw/sbs/historico/FP-1359-oc2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 88064 | 2026-07-04 16:27:17 |
| `data/raw/sbs/historico/FP-1359-oc2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 95232 | 2026-07-04 16:27:23 |
| `data/raw/sbs/historico/FP-1359-oc2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 87040 | 2026-07-04 16:27:27 |
| `data/raw/sbs/historico/FP-1359-se2015.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 139264 | 2026-07-04 16:26:34 |
| `data/raw/sbs/historico/FP-1359-se2016.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 205824 | 2026-07-04 16:26:39 |
| `data/raw/sbs/historico/FP-1359-se2017.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 209920 | 2026-07-04 16:26:45 |
| `data/raw/sbs/historico/FP-1359-se2018.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 123904 | 2026-07-04 16:26:50 |
| `data/raw/sbs/historico/FP-1359-se2019.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 155136 | 2026-07-04 16:26:55 |
| `data/raw/sbs/historico/FP-1359-se2020.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 112640 | 2026-07-04 16:27:01 |
| `data/raw/sbs/historico/FP-1359-se2021.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 111616 | 2026-07-04 16:27:07 |
| `data/raw/sbs/historico/FP-1359-se2022.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 111616 | 2026-07-04 16:27:12 |
| `data/raw/sbs/historico/FP-1359-se2023.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 88064 | 2026-07-04 16:27:17 |
| `data/raw/sbs/historico/FP-1359-se2024.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 92672 | 2026-07-04 16:27:22 |
| `data/raw/sbs/historico/FP-1359-se2025.XLS` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 86528 | 2026-07-04 16:27:27 |
| `data/raw/sbs/sbs_fondo3_20260704_161516.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 4186 | 2026-07-04 16:15:16 |
| `data/raw/sbs/sbs_fondo3_20260704_161708.csv` | No tocar |  | Fuente primaria/raw SBS o mercado; preservar trazabilidad. | 4186 | 2026-07-04 16:17:08 |
| `EJECUTAR_FONDO3.bat` | Mantener |  | Lanzador manual util para operacion local. | 95 | 2026-07-04 21:03:24 |
| `instalar_actualizacion_cobertura_57_60.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 38640 | 2026-07-04 22:49:39 |
| `instalar_tablero_completo_modelo80.py` | Mover a archivo |  | Script raiz de instalacion/correccion/version historica; src contiene la version activa. | 1063 | 2026-07-05 13:15:31 |
| `LEEME_MONITOR_AFP_FINAL.txt` | Mantener |  | Documentacion operativa del proyecto. | 403 | 2026-07-05 20:32:40 |
| `notebooks/.ipynb_checkpoints/01_captura_sbs_fondo3-checkpoint.ipynb` | Posible eliminar |  | Temporal/cache/checkpoint; regenerable, no es fuente canonica. | 1724 | 2026-07-04 21:10:14 |
| `notebooks/01_captura_sbs_fondo3.ipynb` | Mantener |  | Notebook de exploracion/documentacion del modulo inicial. | 55658 | 2026-07-04 16:18:40 |
| `README.md` | Mantener |  | Documento/dependencias base del proyecto. | 1236 | 2026-07-04 21:10:14 |
| `requirements.txt` | Mantener |  | Documento/dependencias base del proyecto. | 116 | 2026-07-04 21:10:14 |
| `SIMULAR MONTO AFP FONDO 3.bat` | Mantener |  | Lanzador manual util para operacion local. | 260 | 2026-07-05 15:58:27 |
| `SIMULAR PERIODO Y VELAS AFP FONDO 3.bat` | Mantener |  | Lanzador manual util para operacion local. | 275 | 2026-07-05 16:07:17 |
| `src/__pycache__/26_depuracion_canonica_ca0001.cpython-313.pyc` | Posible eliminar |  | Temporal/cache/checkpoint; regenerable, no es fuente canonica. | 33235 | 2026-07-04 17:54:15 |
| `src/__pycache__/27_refinar_duplicaciones_ca0001.cpython-313.pyc` | Posible eliminar |  | Temporal/cache/checkpoint; regenerable, no es fuente canonica. | 21972 | 2026-07-04 17:54:15 |
| `src/__pycache__/57_generar_seguimiento_operativo_y_grafica_actual.cpython-313.pyc` | Posible eliminar |  | Temporal/cache/checkpoint; regenerable, no es fuente canonica. | 39968 | 2026-07-04 22:50:30 |
| `src/__pycache__/58_archivar_y_validar_estimaciones_sbs.cpython-313.pyc` | Posible eliminar |  | Temporal/cache/checkpoint; regenerable, no es fuente canonica. | 33657 | 2026-07-04 22:50:30 |
| `src/__pycache__/59_generar_panel_operativo_fondo3.cpython-313.pyc` | Posible eliminar |  | Temporal/cache/checkpoint; regenerable, no es fuente canonica. | 31968 | 2026-07-04 22:50:30 |
| `src/__pycache__/60_orquestar_flujo_operativo_fondo3.cpython-313.pyc` | Posible eliminar |  | Temporal/cache/checkpoint; regenerable, no es fuente canonica. | 13415 | 2026-07-04 22:50:30 |
| `src/__pycache__/69_ampliar_universo_factores_y_screening_train.cpython-313.pyc` | Posible eliminar |  | Temporal/cache/checkpoint; regenerable, no es fuente canonica. | 36880 | 2026-07-05 01:29:23 |
| `src/__pycache__/70_seleccionar_canasta_ampliada_incremental.cpython-313.pyc` | Posible eliminar |  | Temporal/cache/checkpoint; regenerable, no es fuente canonica. | 43571 | 2026-07-05 01:59:26 |
| `src/__pycache__/79_congelar_modelo_y_estimar_prospectivamente.cpython-313.pyc` | Posible eliminar |  | Temporal/cache/checkpoint; regenerable, no es fuente canonica. | 35142 | 2026-07-05 21:07:20 |
| `src/__pycache__/descargar_sbs_actual.cpython-313.pyc` | Posible eliminar |  | Temporal/cache/checkpoint; regenerable, no es fuente canonica. | 8154 | 2026-07-04 16:17:07 |
| `src/02_inspeccionar_historico_sbs.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 7337 | 2026-07-04 16:19:11 |
| `src/03_consolidar_historico_fondo3.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 15612 | 2026-07-04 16:25:12 |
| `src/03_consolidar_historico_fondo3_corregido.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 16283 | 2026-07-04 16:30:39 |
| `src/04_construir_base_maestra_fondo3.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 9786 | 2026-07-04 16:33:46 |
| `src/05_auditar_anomalias_fondo3.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 3437 | 2026-07-04 16:36:05 |
| `src/06_comparar_anomalias_entre_afp.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 5153 | 2026-07-04 16:38:31 |
| `src/07_descargar_factores_mercado.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 14078 | 2026-07-04 16:41:41 |
| `src/08_analizar_correlaciones_factores.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 9407 | 2026-07-04 16:45:30 |
| `src/09_modelo_base_nowcasting.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 13042 | 2026-07-04 16:48:23 |
| `src/10_generar_nowcast_operativo.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 11528 | 2026-07-04 16:52:30 |
| `src/102_tablero_tendencia_y_velas_cuota.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 11166 | 2026-07-05 15:49:48 |
| `src/104_servidor_monitor_celular.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 2735 | 2026-07-05 15:49:48 |
| `src/105_simulador_periodo_y_velas_fondo3.py` | Mantener | Grupo 9 | Script fuente principal del pipeline/modelo/monitor. | 38187 | 2026-07-05 17:07:42 |
| `src/105_simulador_periodo_y_velas_fondo3_BACKUP_20260705_163529.py` | Mover a archivo | Grupo 4 | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 34832 | 2026-07-05 16:07:17 |
| `src/105_simulador_periodo_y_velas_fondo3_BACKUP_20260705_164739.py` | Mover a archivo | Grupo 3 | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 37048 | 2026-07-05 16:35:29 |
| `src/105_simulador_periodo_y_velas_fondo3_BACKUP_20260705_170742.py` | Mover a archivo | Grupo 2 | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 38090 | 2026-07-05 16:47:39 |
| `src/11_registrar_y_validar_nowcast.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 9991 | 2026-07-04 16:54:51 |
| `src/111_vela_pronostico_con_rango_historico.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 20836 | 2026-07-05 17:07:42 |
| `src/113_monitor_final_velas_diarias.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 31846 | 2026-07-05 20:32:38 |
| `src/12_atribucion_dinamica_fondo3.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 14611 | 2026-07-04 16:58:43 |
| `src/13_corregir_fx_y_ortogonalizar_factores.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 17839 | 2026-07-04 17:04:06 |
| `src/14_optimizar_desfase_y_atribucion.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 17785 | 2026-07-04 17:07:41 |
| `src/15_descargar_e_inspeccionar_cartera_fp1356.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 13755 | 2026-07-04 17:12:18 |
| `src/16_exportar_estructura_fondo3_fp1356.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 8281 | 2026-07-04 17:15:49 |
| `src/17_consolidar_cartera_fondo3_fp1356.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 21630 | 2026-07-04 17:18:57 |
| `src/18_auditar_detalle_cartera_fp1356.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 9300 | 2026-07-04 17:21:22 |
| `src/19_mapear_cartera_economica_fp1356.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 17731 | 2026-07-04 17:24:51 |
| `src/20_corregir_mapeo_historico_fp1356.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 24596 | 2026-07-04 17:28:01 |
| `src/21_probar_modelo_con_pesos_reales.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 25374 | 2026-07-04 17:30:58 |
| `src/22_validar_robustez_y_disponibilidad_pesos.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 26781 | 2026-07-04 17:34:42 |
| `src/23_descargar_e_inspeccionar_ca0001.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 15665 | 2026-07-04 17:38:13 |
| `src/24_exportar_estructura_ca0001.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 8722 | 2026-07-04 17:39:55 |
| `src/25_piloto_extraer_fondo3_ca0001.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 21096 | 2026-07-04 17:44:04 |
| `src/26_depuracion_canonica_ca0001.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 28480 | 2026-07-04 17:47:55 |
| `src/27_refinar_duplicaciones_ca0001.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 21601 | 2026-07-04 17:51:01 |
| `src/28_consolidar_historico_ca0001.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 27241 | 2026-07-04 17:53:44 |
| `src/28_consolidar_historico_ca0001_corregido.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 27294 | 2026-07-04 17:57:33 |
| `src/29_reconciliar_ca0001_con_fp1356.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 24313 | 2026-07-04 18:03:57 |
| `src/30_auditar_doble_conteo_ca0001.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 24590 | 2026-07-04 18:07:46 |
| `src/31_auditar_jerarquia_hoja10_ca0001.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 24677 | 2026-07-04 18:11:34 |
| `src/32_auditar_capas_hoja10_ca0001.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 21175 | 2026-07-04 18:14:48 |
| `src/33_construir_base_canonica_hoja10.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 19727 | 2026-07-04 18:17:06 |
| `src/34_auditar_estabilidad_identificadores.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 26448 | 2026-07-04 18:20:23 |
| `src/35_enriquecer_isin_openfigi.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 23545 | 2026-07-04 18:24:11 |
| `src/36_auditar_ambiguedad_y_checksum_isin.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 27345 | 2026-07-04 18:32:20 |
| `src/37_consolidar_identificadores_finales_corregido.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 32166 | 2026-07-04 18:37:33 |
| `src/38_construir_taxonomia_y_proxies_mercado.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 40433 | 2026-07-04 18:41:03 |
| `src/39_refinar_taxonomia_y_proxies.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 31733 | 2026-07-04 18:44:16 |
| `src/40_preparar_exposiciones_publicables.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 20376 | 2026-07-04 18:47:27 |
| `src/41_evaluar_proxies_oos_y_placebos_corregido_v4.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 66724 | 2026-07-04 19:01:01 |
| `src/42_validar_robustez_y_seleccionar_configuracion_corregido.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 34757 | 2026-07-04 19:10:06 |
| `src/43_calibrar_blend_dinamico_y_politica_operativa.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 26638 | 2026-07-04 19:13:07 |
| `src/44_cerrar_configuracion_final_produccion.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 17898 | 2026-07-04 19:15:54 |
| `src/45_ejecutar_motor_operativo_nowcast_corregido_v2.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 45314 | 2026-07-04 19:24:02 |
| `src/46_auditar_semantica_nowcast_actual.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 13384 | 2026-07-04 19:26:01 |
| `src/47_cerrar_nowcast_actual_con_ontologia_modelos.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 24002 | 2026-07-04 19:28:10 |
| `src/48_generar_reporte_operativo_diario.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 25315 | 2026-07-04 19:30:14 |
| `src/49_validar_nowcast_con_datos_oficiales.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 25944 | 2026-07-04 19:32:22 |
| `src/49_validar_nowcast_con_datos_oficiales_corregido.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 27434 | 2026-07-04 19:33:31 |
| `src/50_separar_historico_y_mapear_relaciones.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 39968 | 2026-07-04 20:12:15 |
| `src/51_depurar_canasta_seguimiento_fondo3.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 33090 | 2026-07-04 20:19:37 |
| `src/52_graficar_valor_cuota_sbs_vs_estimado.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 19393 | 2026-07-04 20:22:12 |
| `src/53_simular_desfase_real_publicacion_sbs.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 15633 | 2026-07-04 20:25:24 |
| `src/54_corregir_desfase_calendario_y_auditar_continuidad.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 16317 | 2026-07-04 20:28:13 |
| `src/55_auditar_fechas_faltantes_y_factores.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 18883 | 2026-07-04 20:31:42 |
| `src/56_simular_publicacion_sbs_retrasada_5_dias.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 38219 | 2026-07-04 20:37:49 |
| `src/57_generar_seguimiento_operativo_y_grafica_actual(1).py` | Mover a archivo | Grupo 5 | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 38362 | 2026-07-04 22:44:15 |
| `src/57_generar_seguimiento_operativo_y_grafica_actual.py` | Mantener | Grupo 5 | Script fuente principal del pipeline/modelo/monitor. | 38362 | 2026-07-04 22:50:30 |
| `src/58_archivar_y_validar_estimaciones_sbs(1).py` | Mover a archivo | Grupo 8 | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 33014 | 2026-07-04 22:44:21 |
| `src/58_archivar_y_validar_estimaciones_sbs.py` | Mantener | Grupo 8 | Script fuente principal del pipeline/modelo/monitor. | 33014 | 2026-07-04 22:50:30 |
| `src/59_generar_panel_operativo_fondo3(1).py` | Mover a archivo | Grupo 7 | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 31597 | 2026-07-04 22:44:26 |
| `src/59_generar_panel_operativo_fondo3.py` | Mantener | Grupo 7 | Script fuente principal del pipeline/modelo/monitor. | 31597 | 2026-07-04 22:50:30 |
| `src/60_orquestar_flujo_operativo_fondo3(1).py` | Mover a archivo | Grupo 6 | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 11467 | 2026-07-04 22:44:33 |
| `src/60_orquestar_flujo_operativo_fondo3.py` | Mantener | Grupo 6 | Script fuente principal del pipeline/modelo/monitor. | 11467 | 2026-07-04 22:50:30 |
| `src/61_actualizar_fuentes_sbs_y_mercados.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 30964 | 2026-07-04 22:30:57 |
| `src/62_diagnosticar_series_tiempo_y_ondas.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 27756 | 2026-07-04 23:02:26 |
| `src/63_calcular_metricas_antes_del_entrenamiento.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 24687 | 2026-07-04 23:18:35 |
| `src/63_calcular_metricas_antes_del_entrenamiento_CORREGIDO.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 18553 | 2026-07-04 23:23:06 |
| `src/64_entrenar_comparar_lineales_robustos_ardl.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 45556 | 2026-07-04 23:30:12 |
| `src/65_comparar_arimax_y_modelos_adaptativos.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 39042 | 2026-07-04 23:57:27 |
| `src/65B_corregir_diebold_mariano_modelos_dinamicos.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 6683 | 2026-07-05 00:16:02 |
| `src/65C_diebold_mariano_final_desde_fuentes_separadas.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 9539 | 2026-07-05 00:19:19 |
| `src/66_comparar_no_lineales_y_objetivo_directo.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 56529 | 2026-07-05 00:28:33 |
| `src/67_combinar_modelos_y_validar_estabilidad.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 21890 | 2026-07-05 01:00:19 |
| `src/68_calibrar_amplitud_y_diagnosticar_regimen.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 27482 | 2026-07-05 01:05:18 |
| `src/69_ampliar_universo_factores_y_screening_train.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 34908 | 2026-07-05 01:29:23 |
| `src/69_ampliar_universo_factores_y_screening_train_CORREGIDO.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 33325 | 2026-07-05 01:20:48 |
| `src/69_ampliar_universo_factores_y_screening_train_RESPALDO_20260705_012540.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 31558 | 2026-07-05 01:15:35 |
| `src/69_ampliar_universo_factores_y_screening_train_RESPALDO_DTYPE_20260705_012923.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 34093 | 2026-07-05 01:25:40 |
| `src/70_seleccionar_canasta_ampliada_incremental.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 40067 | 2026-07-05 01:59:26 |
| `src/70_seleccionar_canasta_ampliada_incremental_RESPALDO_NAN_20260705_015926.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 38622 | 2026-07-05 01:43:10 |
| `src/71_evaluar_acciones_individuales_incrementales.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 35616 | 2026-07-05 09:21:25 |
| `src/72_auditar_indices_y_acciones_bvl.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 27422 | 2026-07-05 09:50:59 |
| `src/73_evaluar_aporte_incremental_bvl.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 40111 | 2026-07-05 10:10:46 |
| `src/74_ampliar_indices_internacionales_nativos.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 30859 | 2026-07-05 10:25:12 |
| `src/75_comparar_indices_nativos_vs_etf.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 51466 | 2026-07-05 10:37:16 |
| `src/76_auditar_futuros_commodities_y_cripto.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 24397 | 2026-07-05 10:52:50 |
| `src/77_evaluar_aporte_futuros_commodities_cripto.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 45731 | 2026-07-05 11:04:30 |
| `src/78_consolidar_y_podar_canasta_final.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 39598 | 2026-07-05 11:27:01 |
| `src/79_congelar_modelo_y_estimar_prospectivamente.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 34445 | 2026-07-05 14:14:24 |
| `src/79_congelar_modelo_y_estimar_prospectivamente_BACKUP_20260705_141424.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 31784 | 2026-07-05 11:47:43 |
| `src/79A_graficos_y_correlaciones_finales.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 6081 | 2026-07-05 11:57:50 |
| `src/79C_exportar_ecuaciones_exactas_y_contribuciones.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 14974 | 2026-07-05 12:24:10 |
| `src/80_monitor_sbs_y_validar_pronosticos.py` | Mantener | Grupo 12 | Script fuente principal del pipeline/modelo/monitor. | 35416 | 2026-07-05 13:15:30 |
| `src/80_monitor_sbs_y_validar_pronosticos.py.dashboard_anterior.bak` | Posible eliminar |  | Temporal/cache/checkpoint; regenerable, no es fuente canonica. | 30269 | 2026-07-05 12:48:26 |
| `src/82_monitor_afp_amigable.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 30365 | 2026-07-05 13:29:06 |
| `src/84_monitor_afp_interactivo.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 29048 | 2026-07-05 13:37:10 |
| `src/86_panel_indicadores_afp_intradia.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 31012 | 2026-07-05 13:47:53 |
| `src/90_monitor_afp_solo_estimaciones_validas.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 30184 | 2026-07-05 17:07:42 |
| `src/90_monitor_afp_solo_estimaciones_validas_BACKUP_20260705_143307.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 29762 | 2026-07-05 14:14:24 |
| `src/90_monitor_afp_solo_estimaciones_validas_BACKUP_20260705_154948.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 29880 | 2026-07-05 14:33:07 |
| `src/90_monitor_afp_solo_estimaciones_validas_BACKUP_20260705_160717.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 29987 | 2026-07-05 15:49:48 |
| `src/90_monitor_afp_solo_estimaciones_validas_BACKUP_20260705_170742.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 30087 | 2026-07-05 16:07:17 |
| `src/92_panel_indicadores_didactico.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 28128 | 2026-07-05 17:07:42 |
| `src/92_panel_indicadores_didactico_BACKUP_20260705_143307.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 23467 | 2026-07-05 14:21:09 |
| `src/92_panel_indicadores_didactico_BACKUP_20260705_143710.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 27417 | 2026-07-05 14:33:07 |
| `src/92_panel_indicadores_didactico_BACKUP_20260705_154948.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 28287 | 2026-07-05 14:37:10 |
| `src/92_panel_indicadores_didactico_BACKUP_20260705_160717.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 28394 | 2026-07-05 15:49:48 |
| `src/92_panel_indicadores_didactico_BACKUP_20260705_164739.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 28494 | 2026-07-05 16:07:17 |
| `src/92_panel_indicadores_didactico_BACKUP_20260705_170742.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 28031 | 2026-07-05 16:47:39 |
| `src/97_simulador_monto_fondo3.py` | Mantener | Grupo 9 | Script fuente principal del pipeline/modelo/monitor. | 38187 | 2026-07-05 17:07:42 |
| `src/97_simulador_monto_fondo3_BACKUP_20260705_160717.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 14496 | 2026-07-05 15:58:27 |
| `src/97_simulador_monto_fondo3_BACKUP_20260705_163529.py` | Mover a archivo | Grupo 4 | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 34832 | 2026-07-05 16:07:17 |
| `src/97_simulador_monto_fondo3_BACKUP_20260705_164739.py` | Mover a archivo | Grupo 3 | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 37048 | 2026-07-05 16:35:29 |
| `src/97_simulador_monto_fondo3_BACKUP_20260705_170742.py` | Mover a archivo | Grupo 2 | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 38090 | 2026-07-05 16:47:39 |
| `src/99_cuota_sintetica_intradia.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 42418 | 2026-07-05 15:39:51 |
| `src/99_cuota_sintetica_intradia_BACKUP_20260705_153951.py` | Mover a archivo |  | Copia, respaldo o version marcada para revision; conservar fuera del flujo activo. | 38835 | 2026-07-05 15:36:25 |
| `src/descargar_sbs_actual.py` | Mantener |  | Script fuente principal del pipeline/modelo/monitor. | 6214 | 2026-07-04 21:10:14 |
| `src/instalar_correccion_dtype_modelo69.py` | Mover a archivo |  | Script de instalacion/correccion puntual; no parece parte del flujo activo. | 4991 | 2026-07-05 01:29:04 |
| `src/instalar_correccion_modelo69.py` | Mover a archivo |  | Script de instalacion/correccion puntual; no parece parte del flujo activo. | 4989 | 2026-07-05 01:25:19 |
| `src/instalar_correccion_modelo79_orden.py` | Mover a archivo |  | Script de instalacion/correccion puntual; no parece parte del flujo activo. | 1586 | 2026-07-05 11:46:44 |
| `src/instalar_correccion_modelo79C_dataclass.py` | Mover a archivo |  | Script de instalacion/correccion puntual; no parece parte del flujo activo. | 2320 | 2026-07-05 12:23:41 |
| `src/instalar_correccion_nan_modelo70.py` | Mover a archivo |  | Script de instalacion/correccion puntual; no parece parte del flujo activo. | 4099 | 2026-07-05 01:59:10 |
| `src/LEEME_ACTUALIZACION.txt` | Mantener |  | Documentacion operativa del proyecto. | 1728 | 2026-07-04 22:44:38 |
| `VER CUOTA ESTIMADA INTRADIA AFP.bat` | Mantener |  | Lanzador manual util para operacion local. | 268 | 2026-07-05 15:36:25 |
| `VER INDICADORES AFP EN VIVO.bat` | Mantener |  | Lanzador manual util para operacion local. | 270 | 2026-07-05 13:47:53 |
| `VER INDICADORES DEL MODELO AFP.bat` | Mantener |  | Lanzador manual util para operacion local. | 270 | 2026-07-05 14:21:09 |
| `VER TENDENCIA Y VELAS CUOTA AFP.bat` | Mantener |  | Lanzador manual util para operacion local. | 240 | 2026-07-05 15:49:48 |
| `VER VELA PRONOSTICADA AFP.bat` | Mantener |  | Lanzador manual util para operacion local. | 274 | 2026-07-05 17:07:42 |
