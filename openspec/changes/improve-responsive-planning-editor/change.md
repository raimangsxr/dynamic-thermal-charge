# Editor de planificación responsive

Status: approved

## Goal
Hacer que la creación y edición de una planificación sea comprensible y operable en móvil, tableta y escritorio, sin cambiar el ciclo seguro de vista previa y activación.

## Requirements
- R1: El editor no producirá desplazamiento horizontal de página ni contenido recortado a 390, 768 y 1280 píxeles de ancho.
- R2: Todas las secciones de planificación y previsión serán alcanzables sin depender de pestañas ocultas o controles ambiguos.
- R3: En pantallas estrechas, selección, edición y resumen de acciones se presentarán en una secuencia clara y reversible.
- R4: El estado de cambios pendientes, vista previa, errores y disponibilidad de activación permanecerá visible cerca de las acciones correspondientes.
- R5: La navegación por teclado, foco, etiquetas y orden de lectura conservarán la semántica del formulario.
- R6: Recalcular, descartar y guardar/activar mantendrán sus validaciones, revisiones y tokens actuales.

## Acceptance
- A1: Pruebas de navegador confirman `scrollWidth <= clientWidth` en los tres anchos acordados.
- A2: Se puede editar una regla, recalcular la vista previa y activar usando teclado y usando un viewport móvil.
- A3: Ninguna acción de activación se habilita antes de una vista previa válida y vigente.
- A4: Las pruebas cubren reglas largas, varias estancias, errores de validación y pestañas con textos completos.

## Decisions
- D1: En móvil se priorizará una navegación explícita por secciones sobre la paginación implícita de pestañas Material.
- D2: Se reutilizarán los patrones de `establish-shared-ui-language` y la cobertura de `add-critical-flow-e2e-gate`.

## Tasks
- [x] T1: Corregir el layout y definir el patrón responsive de navegación.
- [x] T2: Reorganizar el flujo móvil y la zona de acciones.
- [x] T3: Añadir pruebas responsive, de teclado y del ciclo de activación.
