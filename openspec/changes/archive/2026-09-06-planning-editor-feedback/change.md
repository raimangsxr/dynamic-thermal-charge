# Feedback fiable para las acciones de planificación

Status: approved

## Goal

Hacer evidente el resultado de las acciones del editor de Nueva planificación.
“Descartar” debe restaurar de inmediato las constraints guardadas y retirar la
preview local; “Guardar y activar” debe distinguir claramente entre operación
en curso, éxito y error.

## Requirements

- R1: “Descartar” restaura las constraints del último plan cargado, limpia la
  preview y el trabajo de preview mostrados localmente, elimina su referencia de
  sesión y muestra un mensaje de confirmación visible.
- R2: Mientras “Guardar y activar” espera respuesta, el botón queda deshabilitado
  y el área de estado indica que se está guardando y activando.
- R3: Una respuesta correcta de activación muestra y conserva un mensaje de éxito
  explícito después de actualizar la proyección del plan, sin que la última
  preview persistida lo sobrescriba.
- R4: Un error de activación muestra un mensaje de alerta explícito, accionable y
  distinto del éxito; el botón vuelve a estar disponible y la preview queda para
  poder corregir o reintentar.
- R5: El flujo de recálculo, cancelación y los contratos HTTP existentes no
  cambian fuera del feedback y el descarte del estado local del editor.

## Acceptance

- A1: Tras editar una constraint y pulsar “Descartar”, los controles recuperan
  los valores guardados, desaparece la preview local y se muestra la confirmación
  de descarte sin esperar un nuevo `GET`.
- A2: Al activar una preview válida, el botón se deshabilita durante la petición
  y, tras una respuesta correcta seguida de un `GET` que incluya la última preview
  persistida, permanece visible el éxito “Planificación guardada y activada
  correctamente.”
- A3: Si la activación responde con error, se muestra `role="alert"` con el
  fallo traducido, no se muestra éxito y el botón vuelve a habilitarse.
- A4: Las pruebas verifican también la limpieza de la referencia de preview en
  `sessionStorage`; frontend tests/build y `make check` pasan.
