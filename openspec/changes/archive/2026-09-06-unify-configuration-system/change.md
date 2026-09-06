# Unificar Configuración y Sistema

Status: approved

## Goal
Eliminar la confusión entre las áreas Configuración y Sistema mediante una única
experiencia de configuración, organizada por tareas y con lenguaje orientado al
operador. La pantalla debe conservar las capacidades existentes y dejar una sola
fuente editable para cada parámetro que hoy aparece duplicado.

## Requirements
- R1: El panel autenticado debe mostrar una única entrada principal “Configuración” y la ruta `/configuracion-sistema` debe redirigir a `/configuracion` para no romper enlaces existentes.
- R2: La pantalla unificada debe cargar y conservar las capacidades de ambos módulos: datos de instalación, CRUD de acumuladores, planificación automática, integraciones, secretos, topología, prueba de conexión, migración de base de datos y actualización meteorológica.
- R3: La información debe organizarse en las áreas “Resumen”, “Instalación”, “Acumuladores”, “Planificación”, “Integraciones” y “Servicio”, con títulos, descripciones, unidades, ayuda contextual y estados de carga/guardado/error comprensibles y adaptables a móvil.
- R4: La interfaz no debe ofrecer controles editables duplicados: `contracted_power_w` será la potencia total canónica; `operations.controller_poll_seconds`, `logging.level` y `operations.retention_days` serán los valores canónicos de operación, registro y retención. Los campos heredados equivalentes quedarán fuera de la experiencia editable.
- R5: La interfaz debe distinguir el modo global de salida del controlador de la asignación física de cada acumulador, y debe explicar que `target_charge` es el valor base mientras que las constraints programadas pertenecen a Planificación.
- R6: Las escrituras deben mantener las revisiones optimistas, las confirmaciones de cambios sensibles, el modo de solo lectura degradado y la regla de que ningún secreto se devuelve ni se conserva en el DOM.

## Acceptance
- A1: El menú lateral contiene una sola entrada “Configuración”; ambas URLs (`/configuracion` y `/configuracion-sistema`) muestran la misma experiencia unificada.
- A2: Cada concepto canónico aparece una sola vez como control editable y los valores heredados `max_total_power_kw`, `poll_seconds`, `log_level` y `retention_days` ya no se presentan como alternativas editables.
- A3: Una edición de instalación, acumulador, planificación o sistema envía la revisión y endpoint actuales; un conflicto conserva los valores introducidos y ofrece releer, y un secreto reemplazado desaparece del DOM tras guardar.
- A4: La potencia mostrada en Estado y usada por la planificación automática procede del mismo valor total canónico, sin divergencia entre ambas vistas.
- A5: La experiencia es navegable por teclado, usa etiquetas asociadas y mensajes de estado accesibles, y mantiene una presentación utilizable en viewport móvil y escritorio.
- A6: Las pruebas frontend y `make check` pasan.

## Outcome
Configuración y Sistema comparten ahora una única experiencia por tareas en
`/configuracion`; se conserva el alias anterior y la compatibilidad de los
datos heredados, mientras que las lecturas operativas usan las fuentes
canónicas definidas por la interfaz.
