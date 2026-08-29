## Purpose

Define el contrato para que toda configuración administrable y sus secretos residan en la base de datos activa, con validación, consistencia y consumo uniforme por todos los procesos.

## ADDED Requirements

### Requirement: La base de datos es la única fuente de configuración runtime
El sistema SHALL obtener de la base de datos activa toda propiedad administrable necesaria para ejecutar la API, el controlador, MQTT, proveedores meteorológicos, drivers de salida, logging, retención, monitorización y pruebas de relés. El sistema MUST NOT leer ficheros de configuración ni variables de entorno como fuente o sobreescritura de esos valores.

#### Scenario: Un valor externo contradice la base de datos
- **WHEN** existe una variable de entorno o un fichero heredado con un valor distinto al almacenado
- **THEN** el sistema usa exclusivamente el valor de la base de datos y avisa de que la fuente heredada se ignora

#### Scenario: Inventario exhaustivo de configuración
- **WHEN** se ejecuta la verificación de configuración del sistema
- **THEN** cada ajuste runtime conocido está registrado en el catálogo persistente o clasificado explícitamente como constante interna o argumento operativo no persistente

### Requirement: La configuración se divide de los datos de aplicación
El driver activo SHALL mantener separados el esquema lógico de configuración de sistema y el esquema lógico de aplicación/runtime, con versiones de migración independientes y sin mezclar secretos en tablas de histórico, planes o estado operativo.

#### Scenario: Inspección de una instalación inicializada
- **WHEN** se inspecciona el driver activo después de aplicar migraciones
- **THEN** se pueden identificar por separado la versión y los objetos de configuración y la versión y los objetos de aplicación/runtime

#### Scenario: Migración exclusiva de configuración
- **WHEN** una versión cambia únicamente el modelo de configuración
- **THEN** se actualiza su versión sin modificar ni recrear el histórico o los planes de aplicación

### Requirement: El catálogo de configuración cubre todos los dominios
El sistema SHALL persistir, como mínimo, selección y conexión de base de datos, API y autenticación, red y CORS, MQTT y credenciales, proveedor meteorológico y API keys, driver de output real o simulado, GPIO, logging, retención, heartbeat, relay test, cadencias y límites operativos, además de la configuración funcional de instalación y acumuladores ya existente.

#### Scenario: Instalación configurada sin fichero externo
- **WHEN** una instalación completa se inicia con sus almacenes locales pero sin fichero de entorno
- **THEN** todos los procesos habilitados obtienen los valores que necesitan y arrancan o informan de campos pendientes de forma accionable

### Requirement: Las actualizaciones son completas, validadas y concurrentes
Toda mutación SHALL validar tipos, rangos, relaciones y compatibilidad global antes de confirmar. SHALL ser atómica, incrementar una revisión y exigir la revisión observada por el cliente para impedir pérdidas silenciosas entre editores.

#### Scenario: Cambio válido
- **WHEN** un administrador guarda una configuración válida indicando la revisión vigente
- **THEN** el cambio se confirma completo, la revisión aumenta y los lectores nunca observan un estado intermedio

#### Scenario: Cambio incompatible o concurrente
- **WHEN** la configuración resultante es inválida o la revisión ya cambió
- **THEN** no se persiste ninguna parte y el error identifica respectivamente los campos inválidos o el conflicto de revisión

### Requirement: Los secretos son write-only en superficies administrativas
Las credenciales y API keys SHALL almacenarse en el esquema de configuración, pero MUST NOT devolverse en claro por API, CLI, frontend, logs, errores, exportaciones de diagnóstico ni documentación generada. Una lectura SHALL indicar únicamente si existe un valor y, cuando sea útil, metadatos no sensibles como la fecha de rotación.

#### Scenario: Lectura de configuración con secretos definidos
- **WHEN** un administrador consulta configuración de MQTT, AEMET, PostgreSQL o autenticación
- **THEN** recibe el estado configurado/no configurado y nunca el secreto, su hash reversible ni una cadena de conexión que lo contenga

#### Scenario: Rotación de un secreto
- **WHEN** un administrador presenta un secreto nuevo válido
- **THEN** se reemplaza atómicamente, no aparece en la respuesta y los procesos que lo consumen adoptan la nueva versión de forma controlada

### Requirement: La protección en reposo tiene un límite explícito
El sistema SHALL proteger los almacenes y sus copias mediante permisos mínimos y SHALL exigir transporte seguro al aceptar credenciales de un PostgreSQL remoto fuera de una red confiable. El sistema MUST NOT afirmar que los secretos están cifrados a nivel de aplicación mientras no exista una raíz de cifrado independiente del propio almacén.

#### Scenario: Configuración de PostgreSQL sin transporte seguro
- **WHEN** un administrador intenta guardar credenciales para un servidor remoto sin TLS y no confirma explícitamente un entorno confiable
- **THEN** la configuración se rechaza con una explicación del riesgo

### Requirement: Los procesos adoptan cambios con semántica conocida
Cada ajuste SHALL declarar si se aplica en caliente, en el siguiente ciclo funcional o después de reiniciar un proceso. El sistema SHALL exponer dicha semántica antes de confirmar y SHALL señalar cualquier reinicio pendiente después del cambio.

#### Scenario: Cambio que requiere reinicio
- **WHEN** se actualiza un ajuste que no puede aplicarse en caliente
- **THEN** el valor queda persistido y el estado administrativo indica qué proceso requiere reinicio sin afirmar que el cambio ya está activo

#### Scenario: Cambio de seguridad aplicable en caliente
- **WHEN** se rota la credencial administrativa
- **THEN** las nuevas solicitudes usan la credencial nueva y la anterior deja de autorizar dentro del límite de propagación documentado

