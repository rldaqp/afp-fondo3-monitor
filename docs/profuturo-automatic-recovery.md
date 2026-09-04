# Recuperación automática de Profuturo

El visor lee archivos estáticos: recargar la página no obtiene nuevas cotizaciones.
`Mantener intradia Fondo 3` supervisa el archivo público y el del repositorio,
sin modificar ecuaciones, coeficientes, cotizaciones ni historial por su cuenta.

- Una sola ejecución permanece activa. Cada tres horas solicita su relevo por
  `workflow_dispatch`, antes del límite de duración de GitHub. Un cron tardío no
  cancela al supervisor activo. Al instalar cambios, el primer relevo se prueba
  en ocho minutos.
- El cron cada tres horas y el evento de finalización de modelos son rescates
  adicionales: el funcionamiento normal ya no espera otro cron para continuar.
- Durante la sesión de NYSE comprueba el corte cada minuto. Si supera cinco
  minutos, falta la sesión actual, hay factores antiguos/incompletos o Pages no
  coincide con el repositorio, solicita el actualizador existente. No duplica
  publicadores activos y limita nuevos intentos a uno cada cinco minutos.
- Usa el calendario XNYS, incluidos feriados, cambios de hora y cierres tempranos.
  Mantiene una ventana de 90 minutos después del cierre para su consolidación.
- Fuera de esa ventana no solicita actualizaciones ni consulta las cotizaciones;
  espera, conservando el relevo automático. Por tanto ocupa un runner estándar
  ligero también entre sesiones para no depender de un nuevo cron de apertura.
- Los publicadores verifican que Pages sirva exactamente el JSON recién generado;
  no basta con que la acción de despliegue termine sin error.

Los mensajes `recuperacion_solicitada`, `publicacion_verificada` y
`relevo_automatico_solicitado` permiten comprobar cada etapa en los logs. El evento
`workflow_dispatch` de estos relevos lo emite el supervisor, no requiere un clic
del usuario.

Una indisponibilidad de GitHub Actions/API puede afectar también al relevo. Esto
reduce la dependencia del cron pero no constituye una garantía de disponibilidad
ni un supervisor alojado fuera de GitHub. El visor mantiene su advertencia de
datos atrasados y los controles externos de apertura/cierre siguen siendo útiles.
Para detener permanentemente el supervisor se deshabilita su workflow en Actions;
cancelar solo una ejecución no desactiva los disparadores de recuperación.
