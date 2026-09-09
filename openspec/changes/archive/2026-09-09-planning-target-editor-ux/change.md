# Rediseñar el editor de consignas de planificación

Status: approved

## Goal

Hacer que añadir y revisar consignas semanales sea claro, ordenado y usable en
escritorio y móvil. La edición debe explicar visualmente cada regla y sus
horarios sin alterar el cálculo, la preview ni la activación existentes.

## Requirements

- R1: Cada consigna se muestra como una tarjeta independiente, con bloques
  reconocibles para acumulador/temperatura, horario, días y estado, sin depender
  de una fila horizontal de controles ni de etiquetas intercaladas.
- R2: La tarjeta muestra un resumen legible de acumulador, temperatura, días y
  horario; sus acciones de duplicar y quitar quedan agrupadas y tienen nombres
  accesibles.
- R3: La selección de días usa controles visuales tipo pastilla con el nombre
  completo disponible para tecnologías de asistencia y conserva los índices
  semanales actuales del payload.
- R4: El horario explica que el inicio se incluye y el fin se excluye, indica
  cuándo una regla cruza medianoche y permite representar explícitamente el fin
  `24:00` como “medianoche”, sin cambiar el contrato de la API.
- R5: El estado vacío, el botón para añadir y las acciones de descartar,
  recalcular y activar forman una jerarquía única y visible; los mensajes de
  proceso, éxito y error permanecen junto a esas acciones.
- R6: Cambiar la presentación no pierde ediciones, previews ni trabajos en
  curso al cambiar de pestaña, y no inicia recalculados automáticos mientras se
  escribe.

## Acceptance

- A1: Con cero consignas se muestra una invitación clara para añadir la primera;
  al añadirla aparece una tarjeta completa y usable.
- A2: En viewport ancho y estrecho, todos los controles de una tarjeta quedan
  agrupados bajo su sección, sin desbordar horizontalmente ni dejar botones
  sueltos.
- A3: Una consigna existente con `end_time: "24:00"` se presenta como
  medianoche; editar el horario ordinario o activar/desactivar medianoche envía
  el valor esperado en preview y activación.
- A4: La tarjeta comunica días seleccionados, intervalo y temperatura en su
  cabecera, y los controles conservan etiquetas y estados accesibles.
- A5: Duplicar, quitar, descartar, recalcular, activar y los mensajes de error
  conservan el comportamiento cubierto por los tests actuales.
- A6: Los tests del frontend y la build de producción pasan.

## Decisions

- D1: No se modifica el backend ni el esquema HTTP; `TemperatureTargetRequest`,
  los índices lunes=0 a domingo=6 y la semántica de intervalos permanecen
  iguales.
- D2: La edición sigue siendo inline y permite ver varias tarjetas a la vez;
  no se introduce un modal para crear o editar reglas.
- D3: El recalculado continúa siendo explícito mediante “Recalcular vista
  previa” para evitar peticiones y cambios de estado mientras el usuario edita.
