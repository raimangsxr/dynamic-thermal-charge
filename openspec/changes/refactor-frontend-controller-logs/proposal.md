## Why

El panel actual cumple las operaciones básicas, pero ofrece una experiencia visual y de navegación demasiado elemental para operar la instalación con rapidez y confianza. Además, diagnosticar el controlador obliga a acceder al sistema anfitrión para leer sus logs, alejando una señal esencial de la interfaz de operación.

## What Changes

- Rediseñar el shell de aplicación y las vistas del panel para aportar jerarquía visual, navegación clara, estados de carga/error/vacío y un uso móvil accesible, preservando las garantías actuales de seguridad y de no operar relés desde el panel.
- Incorporar una vista autenticada, de solo lectura, para consultar los eventos recientes del log del controller desde el navegador, con actualización incremental, niveles de severidad, marcas temporales y controles de filtrado/búsqueda.
- Añadir una interfaz API protegida para entregar un historial acotado de eventos del controller sin exponer archivos arbitrarios ni logs de otros servicios.
- Presentar la salud del controller y sus eventos de diagnóstico como información complementaria y distinguible del estado operativo actual.

## Capabilities

### New Capabilities

- `controller-log-viewer`: exposición autenticada y segura de los eventos recientes del controller y su consulta desde el panel.
- `operator-panel-experience`: experiencia visual, navegación y estados de interfaz coherentes para las áreas operativas existentes del panel.

### Modified Capabilities

- Ninguna.

## Impact

- Frontend Angular: shell de navegación, estilos globales, vistas de estado/configuración/histórico/prueba de relés, capa API y pruebas unitarias.
- API FastAPI: nuevo endpoint de lectura protegido, esquemas y mecanismo acotado para obtener eventos del log del controller.
- Despliegue y operación: configuración del servicio/logging y documentación de la fuente, retención y límites del log visible.
- No se modifica la autoridad del controller sobre los relés: la nueva funcionalidad es exclusivamente de observación.
