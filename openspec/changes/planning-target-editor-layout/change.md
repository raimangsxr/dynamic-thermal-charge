# Editor de consignas: layout y acciones rápidas

Status: draft

## Goal

Alinear el paso `Consignas` con el feedback de diseño, simplificando su jerarquía y sus textos sin cambiar la API, el backend ni el momento en que se inicia una preview. El detalle seleccionado debe concentrar la edición; la lista debe facilitar selección, lectura y acciones rápidas.

## Requirements

- R1: El encabezado del detalle seleccionado contiene el único toggle editable activo/inactivo, vinculado a `enabled` del borrador; al cambiarlo, el indicador textual de estado de solo lectura de la fila correspondiente se actualiza de inmediato. El control o área de selección no contiene controles interactivos anidados y no existe una sección independiente `Estado`.
- R2: El formulario del detalle usa dos columnas: la izquierda es un único bloque que agrupa, en orden, acumulador, temperatura, inicio y fin; la derecha contiene `Días de aplicación`. En anchos reducidos ambas columnas se apilan conservando ese orden, sus etiquetas y asociaciones accesibles.
- R3: Se retiran las ayudas redundantes sobre inicio/fin, medianoche y conservación de consignas inactivas. Las etiquetas directas y accesibles preservan que el inicio es incluido y el fin excluido.
- R4: `select` e inputs `number`/`time` comparten de forma verificable altura calculada, `box-sizing`, tipografía, borde, radio y padding. Las pills de días y los botones no tienen que igualar la altura de esos campos, pero mantienen estados de foco y de selección perceptibles y accesibles.
- R5: Cada fila de lista ofrece botones de icono para duplicar y eliminar como controles hermanos del botón o área de selección, nunca anidados, con nombres accesibles que identifican la acción y la consigna. Cada acción opera sobre la fila accionada sin activar su selección por propagación del evento; duplicar crea una copia independiente de esa consigna y eliminar conserva la confirmación antes de retirar esa consigna. Las acciones ya presentes en el detalle también se conservan.
- R6: Solo el día completo canónico `start_time: "00:00", end_time: "24:00"` se presenta como `00:00–00:00 (día siguiente)` en lista, detalle y resúmenes. Al editar su fin mostrado como `00:00`, el borrador/payload mantiene o canoniza `end_time: "24:00"`; los demás horarios ordinarios y cruces de medianoche conservan sus valores y semántica. No hay toggle ni ayuda específica de medianoche y no cambia el contrato de API/backend.
- R7: Editar el borrador, incluido estado, horario, duplicado o eliminación, no modifica el plan activo ni inicia una preview hasta que el operador solicita la comprobación.

## Acceptance

- A1: Pruebas DOM/comportamiento verifican un solo toggle editable en el encabezado del detalle, la actualización inmediata del indicador no interactivo de la fila correspondiente al cambiarlo, la ausencia de `Estado` independiente y que ningún control interactivo está anidado dentro de otro.
- A2: Pruebas DOM verifican el bloque izquierdo único con acumulador, temperatura, inicio y fin, frente al bloque derecho de días, las etiquetas accesibles y la ausencia de las ayudas retiradas.
- A3: Pruebas de comportamiento verifican las acciones rápidas y las conservadas en el detalle: nombres accesibles, actuación sobre la fila accionada sin seleccionar esa fila por propagación, copia exacta e independiente y confirmación antes de eliminar solo la consigna de la fila accionada.
- A4: Pruebas de comportamiento verifican que solo `00:00`/`24:00` recibe el resumen de día completo y vuelve a producir `end_time: "24:00"` al editar su fin como `00:00`; horarios ordinarios y cruces de medianoche conservan valor y semántica, sin preview automática.
- A5: Una inspección visual en navegador, en viewport amplio y estrecho, confirma las dos columnas y su apilado, la alineación y la igualdad de estilos/altura calculada solo entre `select` e inputs `number`/`time`, y estados de foco/selección perceptibles en pills y botones. No se atribuyen contraste ni geometría a pruebas unitarias sin renderizado real.
- A6: `openspec validate --strict` y `make check` pasan tras la implementación.

## Decisions

- D1: La equivalencia visual `00:00–00:00 (día siguiente)` es exclusiva del día completo canónico; `24:00` sigue siendo la representación de payload. Esta mejora es solo de frontend.

## Tasks

- [ ] T1: Reestructurar lista, encabezado y columnas del detalle, retirar las ayudas indicadas y añadir las acciones rápidas sin retirar las del detalle.
- [ ] T2: Normalizar los estilos de `select` e inputs `number`/`time` y preservar los estados accesibles de pills y botones.
- [ ] T3: Actualizar las pruebas DOM/comportamiento para estado, estructura, acciones, día completo, otros horarios y ausencia de preview automática.
- [ ] T4: Realizar la inspección visual responsive y ejecutar el quality gate.
