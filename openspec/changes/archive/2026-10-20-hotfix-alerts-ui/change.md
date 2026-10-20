# Hotfix visual de Estado y Avisos

Status: approved

## Goal

Alinear Estado y Avisos con la información que ya se muestra en Equipos y con
el lenguaje visual del shell: eliminar la vista duplicada de telemetría,
compactar sin ocultar los avisos y ofrecer una paginación explícita y
comprensible.

## Requirements

- R1: Estado no renderiza la sección independiente `#telemetry-title` ni su tabla después de Equipos; cada tarjeta de Equipo conserva sus lecturas y estado de telemetría.
- R2: El indicador de Avisos del header sigue siendo un enlace a `/avisos`, conserva icono, contador, nombre accesible y contraste suficiente, y reduce su caja/padding visibles para resultar coherente con logout sin perder legibilidad ni el objetivo interactivo.
- R3: Avisos separa visualmente tabs, toolbar (selector de tamaño), lista y paginación, con espacios y bordes que no se solapan ni quedan pegados; la composición sigue siendo usable en móvil.
- R4: Cada tarjeta conserva severidad, fecha, título, cuerpo y acuse cuando corresponda, pero usa espaciado y tipografía compactos para mostrar aproximadamente 5–10 tarjetas por pantalla cuando el contenido lo permita.
- R5: El selector ofrece exactamente `5`, `10`, `20` y `50`, comienza en `10`, y el tamaño elegido se envía en consultas, acuses y páginas siguientes; cambiarlo reinicia el cursor.
- R6: Se sustituye `Cargar más` por un control de paginación claramente identificado, basado en el cursor opaco existente; avanzar muestra la página siguiente sin duplicar la página actual y el final comunica que no quedan resultados.

## Acceptance

- A1: Las pruebas de Estado confirman que no existe `#telemetry-title` ni una tabla independiente y que siguen visibles las lecturas dentro de cada Equipo.
- A2: Las pruebas del shell confirman que el indicador conserva `routerLink="/avisos"`, contador, icono y nombre accesible; la revisión visual confirma que su tratamiento visible no sobresale frente a logout y mantiene contraste/foco.
- A3: Las pruebas o revisión visual de Avisos muestran tabs, toolbar, lista y paginación como zonas distinguibles, sin bordes superpuestos, y tarjetas compactas en viewport ancho y estrecho.
- A4: Las pruebas conservan las opciones y el valor inicial `10`, el `limit` seleccionado en cada operación y el reinicio del cursor al cambiar tamaño.
- A5: Con `has_more`, aparece paginación con una acción tipo `Siguiente página` y no aparece `Cargar más`; se reenvía `next_cursor` literalmente y la lista visible cambia a la página siguiente. Sin `has_more`, se muestra un estado explícito de fin.
- A6: `make check` pasa.

## Outcome

El comportamiento duradero de Avisos queda consolidado en la capacidad viva
`openspec/specs/alerts/spec.md`; la implementación verificada queda lista para
archivarse.
