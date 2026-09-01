# Correcciones de visualización de Planificación

Status: approved

## Goal

Corregir la presentación y carga de los gráficos de Planificación para que los intervalos sean legibles, los gráficos aparezcan al entrar en la vista y el forecast AEMET visible sea el realmente recibido. Eliminar el contenedor visual único y ampliar los detalles bajo demanda.

## Requirements

- R1: Los ejes temporales de intervalos muestran únicamente el instante inicial de cada intervalo; el final no aparece en la etiqueta.
- R2: Al renderizar Planificación, la proyección inicial provoca la creación automática de todos los gráficos que tengan datos, sin pulsar «Actualizar».
- R3: Los diálogos de detalle usan un ancho amplio en escritorio y siguen limitados al viewport en móvil, manteniendo backdrop, cierre explícito y Escape.
- R4: El gráfico de previsión usa los valores de `hourly_points` del forecast más reciente devuelto por `/api/v1/planning`; no sustituye sus temperaturas por `average_temperature_c` ni por un valor fijo.
- R5: La página no está envuelta en una section/card visual global; temperatura por intervalo, carga por acumulador, potencia agregada, carga acumulada y previsión horaria son sections/cards independientes.

## Acceptance

- A1: Las etiquetas de intervalo contienen solo el inicio y las pruebas cubren al menos dos intervalos con inicios distintos.
- A2: Las pruebas verifican la petición inicial y la creación de gráficos tras actualizar la proyección, incluyendo un caso en que la vista se actualiza después de `AfterViewInit`.
- A3: Las pruebas verifican el ancho configurado de ambos diálogos y su cierre accesible.
- A4: Una prueba con forecast asociado al plan simulado y forecast almacenado AEMET más reciente verifica que la respuesta expone el segundo, incluidos sus `hourly_points`.
- A5: Una prueba confirma que las cards de gráficos son sections independientes y no existe un section contenedor de toda la página.
