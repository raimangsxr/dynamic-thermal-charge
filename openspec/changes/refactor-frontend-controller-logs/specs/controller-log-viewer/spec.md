## Purpose

Permite al operador diagnosticar el controller desde el panel sin acceso al host, mediante eventos recientes, autenticados y estrictamente de solo lectura.

## ADDED Requirements

### Requirement: Consulta acotada de eventos del controller
El sistema SHALL ofrecer, bajo la autenticación existente de la API, una consulta paginada de eventos recientes emitidos por el servicio controller. Cada evento SHALL incluir un identificador estable, instante UTC, nivel de severidad, origen y mensaje. La respuesta SHALL estar limitada por el servidor, ordenada de más reciente a más antiguo y permitir solicitar eventos posteriores a un identificador ya visto para actualizar la vista sin duplicados.

#### Scenario: Primera consulta de eventos
- **WHEN** un usuario autenticado solicita los eventos recientes sin cursor
- **THEN** recibe como máximo el límite permitido de eventos del controller en orden descendente y metadatos para continuar la lectura

#### Scenario: Actualización incremental
- **WHEN** el panel consulta eventos posteriores al último identificador que ya muestra
- **THEN** recibe solamente los nuevos eventos disponibles y conserva una secuencia sin repetidos

### Requirement: Aislamiento y acceso de solo lectura
La consulta de eventos SHALL aceptar únicamente los filtros documentados de nivel, texto y paginación. No SHALL aceptar rutas de archivo, nombres de unidad de sistema ni parámetros que permitan leer logs ajenos, y no SHALL modificar el controller, su configuración ni el estado de los relés.

#### Scenario: Solicitud no autenticada
- **WHEN** se consulta el historial de eventos sin una credencial válida
- **THEN** la API rechaza la solicitud igual que el resto de recursos operativos protegidos

#### Scenario: Intento de seleccionar una fuente arbitraria
- **WHEN** un cliente incluye un parámetro para elegir un archivo o servicio de log
- **THEN** la API no revela contenido de esa fuente y no cambia su origen fijo de eventos del controller

### Requirement: Visor de eventos operativo
El panel SHALL proporcionar una ruta protegida de diagnóstico que muestre los eventos con hora local legible, severidad, origen y mensaje; SHALL permitir filtrar por severidad y buscar texto; y SHALL actualizar los eventos recientes sin recargar la página ni alterar los filtros activos. Los eventos de error y advertencia SHALL diferenciarse visualmente sin presentarse como cambios del estado de los relés.

#### Scenario: Filtrado y búsqueda
- **WHEN** el operador selecciona un nivel y escribe un texto de búsqueda
- **THEN** el visor presenta solo los eventos que cumplen ambos criterios e indica cuando no existen coincidencias

#### Scenario: Llegada de un evento nuevo
- **WHEN** llega un evento del controller mientras el visor permanece abierto
- **THEN** el panel incorpora el evento sin reiniciar la vista ni borrar los filtros del operador

### Requirement: Retención segura de eventos visibles
El sistema SHALL conservar únicamente una ventana finita y configurable de eventos consultables del controller. Un fallo al registrar un evento para su consulta web SHALL quedar aislado y no SHALL impedir que el controller continúe con su ciclo de control ni con su registro operativo principal.

#### Scenario: Se supera la retención configurada
- **WHEN** se registra un evento que excede la ventana de retención
- **THEN** los eventos más antiguos dejan de estar disponibles y la consulta sigue siendo acotada

#### Scenario: Falla el almacenamiento del visor
- **WHEN** el almacenamiento de eventos consultables no está disponible
- **THEN** el controller continúa su operación de forma segura y el fallo queda registrado por el mecanismo operativo disponible
