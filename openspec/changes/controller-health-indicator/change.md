# Indicador de salud del controlador junto a Actualizar

Status: approved

## Goal
En la página Estado, mostrar junto a Actualizar una señal compacta y accesible del
estado real del controlador, con el detalle disponible sin ocupar el panel principal.
La propuesta se apoya en `frontend/src/app/status/status.html` (cabecera y botón),
`frontend/src/app/status/status.ts` y `frontend/src/app/core/api.ts` (lectura y
refresco de `/api/v1/status`), `frontend/src/app/core/api.types.ts` (el contrato
`ControllerHealthDto`) y `frontend/src/app/status/controller-health/controller-health.ts`
(la explicación existente de liveness); las pruebas
`frontend/src/app/status/status.spec.ts` y
`frontend/src/app/status/controller-health/controller-health.spec.ts` fijan las
semánticas que no deben regresar.

## Requirements
- R1: El indicador debe derivar su estado de `StatusDto.controller` recibido por `/api/v1/status`, sin convertir la ruta `/health` en una comprobación del controlador ni cambiar el contrato de ninguna API.
- R2: Debe aparecer en la cabecera, junto al botón Actualizar, solo después de un resultado inicial correcto o de un fallo real de lectura. El estado visual es verde para `live` sin sospecha de duplicidad, amarillo para `live_degraded` o `live` con `multiple_controllers_suspected`, y rojo para `stale`, `never_seen` o un fallo de lectura.
- R3: El detalle debe conservar la información ya presentada por `ControllerHealth`: situación y explicación, antigüedad/última señal cuando exista, arranque y tipo de salidas cuando proceda, orientación de comprobación, consecuencias de `state_is_current` y la alerta de múltiples controladores cuando corresponda.
- R4: En dispositivos con puntero, el detalle debe estar disponible al pasar el puntero por el indicador; en dispositivos táctiles, al tocarlo. El mismo control debe poder enfocarse y activarse con teclado, y su nombre/estado/detalle deben ser comprensibles para lector de pantalla; el color no puede ser la única señal.
- R5: Un fallo de refresco debe poner el indicador en rojo y explicar que el estado actual no se puede confirmar, aunque la vista conserve el último snapshot y su banner de error según el comportamiento actual de `status.ts`.

## Acceptance
- A1: Las pruebas cubren carga inicial (indicador oculto), `live`, `live_degraded`, `stale`, `never_seen` y `multiple_controllers_suspected`, verificando texto accesible y el estado/color correspondiente.
- A2: Tras un snapshot `live`, un fallo de `/api/v1/status` deja el snapshot visible pero cambia el indicador a rojo y expone el detalle de no confirmación; una lectura posterior actualiza el indicador al nuevo liveness.
- A3: Las pruebas verifican detalle por hover/foco, por tap/activación y por teclado, incluido el anuncio del estado para lector de pantalla sin depender solo del color.
- A4: Las pruebas existentes de `status.spec.ts` y `controller-health.spec.ts` siguen demostrando que no se inventan potencia ni estados de salida cuando `state_is_current` es falso, y que el healthcheck actual conserva sus cuatro situaciones.
- A5: No se añade una llamada al endpoint `/health`, no se modifica su respuesta deliberadamente muda (cubierta por `backend/tests/test_api_security.py`) y se mantienen el polling y el refresco manual existentes.

## Decisions
- D1: La fuente es `controller.liveness` de `/api/v1/status`, no `/health`: `backend/src/dynamic_thermal_charge/api/routes/health.py` confirma que `/health` solo prueba que responde el proceso API y no revela la instalación.
- D2: Se usan tres estados cromáticos: verde (`live` normal), amarillo (`live_degraded` o sospecha de varios controladores) y rojo (`stale`, `never_seen` o error de lectura). Esta decisión concilia la petición visual con la advertencia operativa existente en `controller-health.ts`.
- D3: Durante la carga inicial se oculta el indicador; ante cualquier fallo de lectura, incluso con snapshot previo, pasa a rojo. El snapshot permanece visible como información no actual, conforme a `status.ts` y `status.spec.ts`.

## Tasks
- [x] T1: Añadir al encabezado el indicador y su estado derivado, sin alterar el flujo de refresco ni la semántica de `ControllerHealth`.
- [x] T2: Exponer el detalle por puntero, toque y teclado con nombre/relaciones ARIA adecuados y una señal textual independiente del color.
- [x] T3: Ampliar las pruebas frontend relevantes para estados, fallo de lectura e interacción accesible; ejecutar el conjunto determinista frontend.
