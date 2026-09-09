# Editor de consignas con lista y detalle

Status: approved

## Goal

Sustituir el editor de tarjetas repetitivas por una composición master-detail
que aproveche mejor el espacio en escritorio y siga siendo clara en móvil. La
edición continuará usando el borrador y el flujo de preview/activación actuales.

## Requirements

- R1: En escritorio, Nueva planificación muestra a la izquierda una lista vertical compacta de consignas y a la derecha el detalle editable de una única consigna seleccionada.
- R2: Cada elemento de la lista resume acumulador, temperatura, días, horario y estado; seleccionar una consigna actualiza el detalle sin recalcular ni perder ediciones.
- R3: El detalle conserva los bloques editables de valores, horario, días y estado, además de duplicar y quitar agrupados; añadir y duplicar seleccionan la consigna resultante.
- R4: Con cero consignas se muestra una invitación para crear la primera y no se muestra un formulario vacío; al quitar la última se vuelve a ese estado.
- R5: En viewport estrecho la lista y el detalle se apilan, sin scroll horizontal ni scroll interno anidado; la lista y todos sus controles mantienen nombres y estados accesibles.
- R6: Descartar, recalcular, activar, preview, trabajos en curso y cambios de pestaña conservan su comportamiento; el payload completo de consignas y la semántica de `24:00` no cambian.

## Acceptance

- A1: Con varias consignas, el escritorio muestra una sola edición a la derecha y la lista izquierda permite cambiar de regla conservando el borrador.
- A2: Añadir, duplicar, quitar y descartar mantienen una selección determinista y los valores editados; cambiar de selección no inicia una petición.
- A3: La vista vacía permite añadir la primera consigna y presenta inmediatamente su detalle completo.
- A4: En escritorio y móvil se leen los resúmenes, la selección, los días completos, el intervalo inclusivo/exclusivo y `24:00` como medianoche.
- A5: Los tests del editor y `make check` pasan sin cambios de backend ni del contrato HTTP.

## Decisions

- D1: El guardado persistente sigue siendo global mediante `Guardar y activar`; no se añade guardado independiente por consigna ni un endpoint nuevo.
- D2: La primera consigna queda seleccionada inicialmente; una nueva o duplicada queda seleccionada; al quitar se selecciona la vecina disponible y con cero consignas se muestra el estado vacío.
- D3: La selección solo cambia la presentación. Editar actualiza el borrador local y `Recalcular vista previa` sigue siendo explícito.
