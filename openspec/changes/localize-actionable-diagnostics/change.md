# Diagnóstico localizado y accionable

Status: approved

## Goal
Convertir el registro técnico en una herramienta de diagnóstico comprensible para el operador, conservando íntegros los detalles necesarios para soporte.

## Requirements
- R1: Los eventos conocidos mostrarán título, resumen, severidad y origen funcional en español.
- R2: El código, origen y mensaje técnicos originales permanecerán disponibles en un detalle expandible y copiable.
- R3: Los eventos con una acción conocida mostrarán la misma recomendación y destino que Estado y Planificación.
- R4: Los eventos desconocidos usarán un fallback neutro, conservarán el contenido original y no inventarán una causa o solución.
- R5: La lista será legible sin columnas comprimidas en móvil y conservará una tabla eficiente en escritorio.
- R6: Filtros, orden cronológico y semántica de severidades no cambiarán.

## Acceptance
- A1: Pruebas cubren eventos conocidos, desconocidos y mensajes sin traducción.
- A2: El usuario puede copiar el detalle técnico sin que sea el contenido dominante por defecto.
- A3: Las acciones de remediación coinciden con el catálogo de códigos compartido.
- A4: La vista no presenta desbordamiento horizontal a 390 píxeles.

## Decisions
- D1: No se traducirá en backend texto libre histórico; el frontend presentará códigos conocidos y preservará el original.
- D2: Este cambio depende de `establish-shared-ui-language` y `add-planning-recovery-guidance`.

## Tasks
- [x] T1: Definir el catálogo de eventos, orígenes y fallbacks.
- [x] T2: Implementar detalle técnico, remediación y layout responsive.
- [x] T3: Añadir pruebas de presentación, navegación y copia.
