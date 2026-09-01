# Shell fija y reorganización de Planificación

Status: approved

## Goal

Hacer más accesible el panel manteniendo header y navegación visibles durante el scroll, y reorganizar Planificación para que los resúmenes sean escaneables, los detalles estén bajo demanda y los gráficos representen correctamente la previsión horaria recibida.

## Requirements

- R1: El header ocupa todo el viewport, permanece fijo arriba y contiene un botón para abrir y cerrar el menú lateral; en escritorio el menú empieza abierto y en móvil conserva el comportamiento responsive existente.
- R2: El menú lateral permanece fijo mientras se desplaza el contenido principal; el main dispone de su propio desplazamiento sin quedar oculto bajo el header.
- R3: Al entrar en Planificación se solicita y renderiza automáticamente la proyección, incluyendo los gráficos cuando existen datos, sin exigir pulsar «Actualizar».
- R4: Las etiquetas horizontales de los gráficos de intervalos muestran una referencia cada cinco intervalos y dejan las restantes vacías; al pasar el cursor por cualquier punto se muestra su intervalo completo y sus valores concretos.
- R5: Forecast y planificación tienen cada uno una card resumen con un botón que abre su detalle en un popup accesible con backdrop y cierre explícito.
- R6: Las fechas de Planificación se muestran con un formato compacto en español, legible y consistente, incluyendo hora y minuto cuando corresponda.
- R7: El gráfico de previsión horaria representa los valores de `hourly_points` devueltos por la API, incluidos valores distintos de la media simulada, y no queda fijado en 8 °C cuando AEMET ha respondido correctamente.
- R8: Cada bloque de planificación (temperatura, carga por acumulador, potencia agregada y carga acumulada) se presenta como una card independiente, manteniendo una representación tabular accesible.
- R9: La primera card de Planificación explica el estado de los datos: origen legible, fecha, rango temporal, número de registros horarios, temperaturas resumen, última consulta y próxima consulta cuando estén disponibles; no muestra «simulado» ni «48 puntos» sin contexto.

## Acceptance

- A1: Las pruebas del shell verifican toolbar a ancho completo, botón visible en escritorio y apertura/cierre del sidenav.
- A2: Las pruebas de Planificación verifican la petición inicial, la creación/render posterior de los gráficos, las cards independientes, los botones de detalle, el popup con backdrop y los formatos de fecha.
- A3: Una prueba de gráfico con temperaturas horarias distintas confirma que los datos del dataset son esos valores y que la media configurada no los reemplaza.
- A4: Una prueba verifica etiquetas solo en índices 0, 5, 10… y tooltip con información del intervalo solicitado.
- A5: `npm test`, `npm run build` y `make check` pasan.

## Decisions

- D1: Se conserva la navegación móvil actual (drawer tipo `over`, cerrado inicialmente y cerrado al navegar); el cambio de estado inicial solicitado aplica al escritorio.
- D2: La regla de una etiqueta cada cinco posiciones se aplica a los ejes temporales de todos los gráficos de Planificación; el tooltip sigue disponible en todas las posiciones, incluido forecast.
- D3: El detalle se implementa con el diálogo accesible de Angular Material, usando backdrop, botón de cierre y cierre al pulsar Escape; no se añade una ruta nueva.
