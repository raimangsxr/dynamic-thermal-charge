## Context

El frontend Angular consume una API FastAPI protegida por bearer token y está compuesto por rutas funcionales con un shell y estilos mínimos. El controller y la API son procesos separados: el primero escribe sus logs en consola para systemd/journald y la API no debe importar el controller ni el stack de drivers. Por tanto, leer directamente el journal desde la API añadiría permisos, acoplamiento y superficie de exposición innecesarios.

Las garantías actuales son inviolables: el panel no puede operar salidas, el estado no confirmable no puede presentarse como actual y la API permanece protegida. Véanse los requisitos de las capacidades `controller-log-viewer` y `operator-panel-experience`.

## Goals / Non-Goals

**Goals:**

- Hacer los eventos recientes del controller consultables por la API sin acceso al sistema de archivos, journal ni otros servicios.
- Mantener una carga de control segura: registrar un evento para la web nunca bloquea ni detiene el control térmico.
- Establecer un sistema visual reutilizable para que todas las vistas operativas tengan navegación, jerarquía y estados homogéneos.
- Mantener el frontend desplegable como estático detrás del mismo proxy y la autenticación existente.

**Non-Goals:**

- No ofrecer una consola de sistema, streaming de todos los logs, descarga de archivos ni búsqueda global en el host.
- No cambiar las reglas de planificación, el control de relés, la autenticación ni los contratos existentes de estado, configuración e histórico.
- No rediseñar el backend como tiempo real basado en WebSocket; la actualización del visor será polling incremental.

## Decisions

### Persistir una proyección acotada de los eventos del controller

Se añadirá una tabla propia de eventos de diagnóstico en la misma persistencia ya compartida por controller y API. Un handler de logging específico del proceso controller transformará los registros adecuados en filas con id monotónico, instante UTC, nivel, logger y mensaje ya formateado. Aplicará retención por cantidad/edad configurable y usará un manejo de errores aislado para que una caída de la persistencia no interfiera con el ciclo de control.

La API leerá esta proyección mediante el límite de persistencia existente; no importará `controller`, `drivers` ni consultará journald. Esta separación permite que el servicio API conserve sus restricciones de systemd y que el origen fijo de la API sea auditable.

Alternativas consideradas:

- Consultar `journalctl` desde la API: se descarta porque requiere permisos adicionales, permite mezclar servicios y hace difícil limitar la superficie de lectura.
- Escribir un fichero de log compartido: se descarta por rotación, permisos y acceso concurrente entre procesos.
- Enviar eventos por WebSocket/SSE: se descarta en esta fase; polling con `after_id` aprovecha el patrón actual de refresco y simplifica nginx y la recuperación ante desconexiones.

### Contrato de lectura con paginación e incrementalidad

La ruta protegida será `GET /api/v1/controller-log`. Aceptará únicamente `limit`, `before_id`, `after_id`, `level` y `q`, validará sus rangos y devolverá una página de eventos junto con los cursores/metadatos necesarios. La primera carga usará orden descendente; el refresco con `after_id` se normalizará cronológicamente en el cliente antes de incorporarlo, para no alterar la lectura. El servidor impondrá un máximo de página aunque el cliente solicite más.

`q` se aplicará al texto del mensaje, con coincidencia segura y acotada, y `level` se limitará a los niveles publicados. No se añadirán parámetros de fuente o archivo.

### Shell y primitives visuales compartidos

El root component se convertirá en un shell autenticado con marca, navegación responsive y una región principal. Los estilos globales definirán tokens de color/espaciado/tipografía, superficies, botones, formularios, tarjetas, banners de estado, tablas responsivas y foco visible. Las vistas actuales se migrarán progresivamente a esas primitives sin alterar sus llamadas ni reglas de negocio.

Cada vista conservará el último resultado confirmado durante un error de refresco, mostrará un banner recuperable con reintento y declarará explícitamente sus estados de carga y vacío. El status seguirá usando el contrato de liveness existente como única fuente de verdad para datos actuales.

### Nueva ruta de diagnóstico con polling controlado

Se añadirá la ruta Angular `/diagnostico`, bajo el guard de credencial. Su componente mantendrá filtros locales, consulta la página inicial y usa polling sólo mientras la ruta esté activa. Incorporará los registros por id, evitará duplicados y limitará el buffer cliente; pausará o reducirá la actividad cuando la pestaña no esté visible. Los filtros se conservarán entre actualizaciones, mientras que cargar más resultados será una acción explícita.

## Risks / Trade-offs

- [Los mensajes de log pueden incluir información sensible] → limitar el origen al controller, documentar que no se registren secretos, mantener bearer auth y no exponer el visor sin autenticación.
- [La persistencia adicional incrementa escrituras en una Pi] → usar una ventana pequeña configurable, índice por id/instante, excluir o muestrear niveles muy verbosos y purgar en lotes.
- [Una actualización puede reordenar resultados al aplicar filtros] → tratar la primera página y los nuevos eventos como flujos separados, deduplicados por id, y mantener explícitamente el orden visible.
- [Un cambio visual puede ocultar avisos críticos] → pruebas de componentes para liveness y relay-test, contraste/foco y revisión responsive antes de despliegue.

## Migration Plan

1. Introducir migración, configuración y handler de proyección; desplegar controller primero para empezar a acumular eventos.
2. Desplegar la API con la nueva ruta protegida y verificar límites, autorización y ausencia de dependencia sobre journal/driver.
3. Desplegar el frontend rediseñado; los clientes antiguos continúan funcionando porque no se cambia ningún endpoint existente.
4. Si se requiere rollback, retirar el frontend o la ruta nueva sin afectar al controller; la tabla de eventos puede permanecer inactiva y la migración no elimina datos operativos existentes.
