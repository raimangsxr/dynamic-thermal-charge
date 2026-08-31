# Design

## Approach

Añadir `HourlyForecastPoint` al modelo de previsión sin eliminar los campos diarios existentes. El proveedor AEMET hará dos peticiones (envelope y `datos`), interpretará las horas locales del municipio con la zona horaria de la instalación y normalizará los puntos. Los proveedores simulado y fallback producirán puntos constantes para mantener el contrato.

El cálculo térmico obtendrá la media de los puntos que intersectan la ventana y generará las demandas totales actuales. El scheduler recibirá una temperatura por intervalo, ordenará la asignación por frío y aplicará su capacidad/prioridad determinista. Las horas sin punto usarán la media diaria y una marca explícita.

Persistir los puntos en una tabla hija `forecast_hour` vinculada a `forecast`, con migración Alembic nueva. Ampliar la frontera de lectura para seleccionar el plan que contiene el instante o el próximo plan futuro y devolverlo junto con sus puntos, asignaciones y metadatos de acumuladores en `GET /api/v1/planning`.

La pantalla Angular será un componente lazy de la ruta `/planificacion`. Usará `Chart` de Chart.js sobre canvas para la serie de temperatura y gráficos de barras apiladas/por acumulador; la misma información se renderizará en una tabla HTML y se mantendrá el scroll dentro de los gráficos.

La respuesta de planificación añadirá una línea temporal de 48 horas completas,
alineada con los intervalos del plan aceptado. Para cada acumulador guardará la
reserva equivalente en minutos: se suma carga en los intervalos asignados y se
aplica la pérdida térmica configurada cuando no hay carga, usando el delta entre
la temperatura objetivo y la previsión.

## Constraints

- Las temperaturas AEMET son horas locales sin offset fiable en el payload; la zona horaria de `ScheduleConfig` será la autoridad para convertirlas a instantes comparables.
- El controlador debe poder continuar con el fallback actual si AEMET falla; la persistencia de observabilidad nunca puede detener el bucle.
- Las columnas físicas seguirán representándose en vatios/minutos y los endpoints protegidos mantendrán la semántica actual de credenciales y estado no confirmado.
- La dependencia frontend debe ser compatible con Angular 22 y respetar el presupuesto de bundle existente; no se añade un wrapper adicional si Chart.js directo es suficiente.

## Decisions

- `forecast_hour` se normaliza en filas en lugar de JSON para consultar, validar y migrar los puntos de forma uniforme en SQLite/PostgreSQL y aplicar la retención junto con su previsión padre.
- El endpoint nuevo no recalcula: lee el plan que ya aceptó el controlador. Esto evita que una consulta del panel produzca un plan distinto del que gobierna las salidas.
- Los slots se generan en orden cronológico, pero la asignación se decide por temperatura ascendente; los empates usan el índice temporal y después las reglas actuales para que el resultado sea reproducible.
- Se conservará `GET /status` y su resumen diario; la serie completa será parte del contrato de planificación para limitar el impacto sobre clientes existentes.

## Risks

- La forma del payload horaria de AEMET puede contener horas como claves de texto y valores no numéricos; el parser debe omitir campos opcionales, exigir temperatura para un punto y fallar de forma controlada si no cubre la ventana.
- Una ventana configurada fuera del horizonte recibido puede no tener datos horarios; el fallback diario/interpolado debe quedar señalado en la respuesta y en la UI, sin ocultar la pérdida de detalle.
- Chart.js requiere destruir y recrear/actualizar las instancias al cambiar el snapshot; el componente debe liberar las instancias al destruirse para evitar fugas durante navegación.
