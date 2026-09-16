# Consistencia de vistas previas y diagnóstico de planificación

Status: approved

## Goal

Evitar que una vista previa obsoleta o ya activada se presente como candidata
actual, manteniendo la protección por token. Completar el diagnóstico visible y
hacer que los errores y comprobaciones sean comprensibles para el operador.

## Requirements

- R1: La respuesta de planificación solo expondrá como vista previa recuperable
  el trabajo cuyo payload de consignas y revisiones de configuración coincidan
  con los valores guardados actuales; los trabajos incompatibles seguirán
  consultables por su identificador para auditoría, pero no reaparecerán como
  candidato después de recargar.
- R2: El editor impedirá activar una vista previa cuyo payload de consignas no
  coincida con el borrador actual. Si el token de la vista previa ya coincide
  con el plan activo, la mostrará como informativa y no ofrecerá una activación
  duplicada.
- R3: Un rechazo por cambios de entradas vivas o de revisión devolverá un error
  estable y accionable, se mostrará en español indicando que hay que recalcular
  y conservará la vista previa para poder corregir y reintentar. Nunca se
  relajará la validación ni se activará un resultado obsoleto.
- R4: Los detalles de problemas de un modelo energético incluirán la energía
  almacenada en el instante observado cuando esté disponible; si no existe una
  medida/modelado válido se conservará `null` y se mostrará “no disponible”,
  sin inventar valores. El nombre de la comprobación `room_model` se traducirá
  en todas las vistas.

## Acceptance

- A1: Tras calcular una vista para una consigna distinta, descartarla y recargar,
  no aparece esa vista como candidata ni se habilita “Guardar y activar”.
- A2: Tras activar correctamente una vista y recargar, el plan activo permanece
  visible y la vista persistida se identifica como ya activa, sin acción de
  activación duplicada.
- A3: Si se modifica una consigna después de calcular, el botón de activación
  queda bloqueado y la interfaz indica recalcular; si cambia la telemetría o la
  previsión durante la activación, la API rechaza y la interfaz ofrece el mismo
  siguiente paso en español.
- A4: Los diálogos de problemas muestran la energía almacenada modelada en el
  intervalo correspondiente y mantienen “no disponible” cuando realmente falta;
  ninguna comprobación muestra el identificador técnico `room_model`.
- A5: Las pruebas backend/frontend cubren estos casos y `make check` continúa
  pasando.

## Decisions

- D1: Descartar no elimina trabajos persistidos: se conserva la trazabilidad,
  pero solo un trabajo compatible puede restaurarse como candidato.
- D2: Una vista cuyo token ya gobierna el plan activo permanece consultable como
  información, etiquetada como “ya activa”, con la activación deshabilitada.
- D3: No habrá recálculo automático ni reintento silencioso tras un conflicto de
  token; el operador debe solicitar explícitamente una nueva vista previa.
