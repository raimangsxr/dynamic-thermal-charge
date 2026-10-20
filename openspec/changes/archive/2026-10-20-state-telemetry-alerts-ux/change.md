# Estado, telemetría y bandeja de avisos

Status: approved

Classification: STANDARD

## Goal

Alinear el panel operativo con el modelo actual de telemetría, planificación y
previsión: cada acumulador explica sus lecturas sin cambiar de sección, los
avisos de planificación viven junto al plan y la bandeja de avisos es compacta
y paginable. La consulta AEMET obedece la configuración visible y comunica su
próximo estado incluso cuando todavía no hay telemetría.

## Requirements

- R1: Cada artículo existente de Equipos (`data-heater`) muestra temperatura
  interior y SOC asociados por `heater_id` cuando son utilizables, y un estado
  explícito de falta, caducidad o calibración en caso contrario. Lecturas
  conserva el detalle completo; no se inventan ceros ni valores actuales.
- R2: Los avisos de asignaciones incumplidas, convergencia, mejor esfuerzo,
  resultado degradado y déficits aparecen una sola vez al final de
  Automatización, después del resumen del plan. El aviso específico de
  calibración permanece fuera.
- R3: El ciclo automático usa `weather.refresh_minutes` entre consultas AEMET
  correctas y `weather.retry_minutes` tras un error, respetando `next_cycle`.
  API y configuración exponen el próximo instante y si es actualización o
  reintento; `planning.aemet_query_hour` solo ancla el inicio diario.
- R4: Sin telemetría utilizable, incluido cero elementos `ready`, Estado sigue
  mostrando el próximo estado AEMET con los campos existentes. Sin instante
  programado muestra una ausencia explícita y localizada, nunca una hora
  fabricada.
- R5: Estado no renderiza el botón de actualización de cabecera ni
  `dtc-controller-health`; conserva sondeo automático, indicador compacto de
  salud y reintento únicamente ante error de lectura.
- R6: El indicador de avisos conserva enlace, contador y nombre accesible, con
  control de 48 px y glifo de 24 px, como cerrar sesión.
- R7: Avisos conserva Activas/Histórico y paginación por cursor, con filas o
  tarjetas compactas y espaciado responsive. El selector ofrece exactamente
  `5/10/20/50`, empieza en 10, y consultas, acuses y páginas siguientes usan
  ese tamaño; cambiarlo reinicia el cursor.

## Acceptance

- A1: Las pruebas de Estado cubren telemetría lista, incompleta/caducada, en
  calibración y sin elementos `ready` en cada tarjeta, junto con el próximo
  estado AEMET; no existen `data-testid="refresh-status"` ni
  `dtc-controller-health`, y el indicador compacto es accesible.
- A2: Las pruebas de Estado verifican que cada aviso de planificación está una
  sola vez, dentro y al final de Automatización; las pruebas de honestidad del
  controlador siguen pasando.
- A3: Las pruebas backend/configuración demuestran que `refresh_minutes` y
  `retry_minutes` cambian el próximo ciclo y `forecast_next_run_*`, y que
  Estado y Meteorología son consistentes sin telemetría.
- A4: Las pruebas de Avisos verifican la petición inicial `limit=10`, opciones,
  reinicio de cursor al cambiar tamaño y conservación de vista/tamaño en
  paginación y acuse; la comprobación responsive confirma que caben 5–10
  avisos sin scroll de página cuando el viewport lo permite.
- A5: `make check` pasa y no cambian contratos de alertas, autenticación ni
  persistencia ajenos al cambio.
