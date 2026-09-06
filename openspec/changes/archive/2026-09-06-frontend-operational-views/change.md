# Refactor UX/UI de las vistas operativas

Status: approved

## Goal

Unificar Estado, Histórico y Diagnóstico con el lenguaje visual y los patrones de interacción ya usados por Planificación, Configuración y Prueba de relés. Mejorar la jerarquía de información, la lectura rápida, los estados de carga/error/vacío y la adaptación móvil sin cambiar el comportamiento de dominio.

## Requirements

- R1: Las tres vistas usan una cabecera de página, espaciado, superficies, tipografía, botones Material y estados visuales coherentes con las vistas operativas existentes.
- R2: Estado presenta de forma jerárquica la salud del controlador, los indicadores, los acumuladores, el plan, la telemetría y la previsión; distingue con texto e iconos los estados actual, obsoleto, no disponible y vacío, y ofrece actualización manual además del refresco automático.
- R3: Histórico organiza pestañas, filtros, tablas y paginación en paneles consistentes; conserva los endpoints, filtros, orden recibido, cursores opacos, avisos de previsión de reserva y acumuladores retirados.
- R4: Diagnóstico organiza filtros, actualización, tabla de eventos y carga de páginas anteriores en el mismo sistema visual; conserva la búsqueda, el nivel, el refresco visible de 5 s y el orden/paginación actuales.
- R5: En móvil no aparece desplazamiento horizontal de página; las tablas lo gestionan dentro de su propio contenedor y controles, mensajes, foco visible y regiones de estado siguen siendo utilizables y comprensibles sin depender solo del color.

## Acceptance

- A1: Estado, Histórico y Diagnóstico comparten la jerarquía visual de cabecera/panel/resumen y controles Material de Planificación, Configuración y Prueba de relés.
- A2: Las pruebas existentes siguen pasando y cubren que las garantías de estado no actual sean intactas, que Histórico mantenga sus filtros/cursores y que Diagnóstico mantenga filtros, refresco y carga anterior.
- A3: Las tres vistas tienen pruebas para carga, error recuperable, resultado vacío y contenido con datos, incluyendo los nombres `data-testid` relevantes para sus acciones principales.
- A4: `npm test -- --watch=false` y `npm run build` terminan correctamente en `frontend`.
- A5: No se modifican rutas, contratos API, tipos compartidos ni comportamiento del backend.

## Outcome

Las tres vistas se han alineado con la jerarquía de cabecera, paneles, tarjetas, controles Material y estados accesibles del resto de la aplicación. Se preservan API, rutas, polling, paginación y garantías de datos no confirmados; el frontend queda con 205 tests correctos y build de producción válido.
