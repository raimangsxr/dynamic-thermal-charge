## Purpose

Define la topología de cuatro almacenes lógicos, la selección segura del driver activo y la continuidad local durante la indisponibilidad de PostgreSQL remoto.

## ADDED Requirements

### Requirement: SQLite local de bootstrap siempre disponible
Toda instalación SHALL disponer de un almacén SQLite de bootstrap en una ubicación local determinista y protegida. Este almacén SHALL contener solo el estado de inicialización, el locator y credenciales del driver activo, versiones mínimas y metadatos necesarios para abrir el sistema antes de acceder al backend canónico.

#### Scenario: Primer arranque sin estado previo
- **WHEN** el servicio arranca y el almacén de bootstrap no existe
- **THEN** crea de forma atómica una instalación no configurada con valores seguros y permite iniciar el onboarding sin requerir un fichero

#### Scenario: Arranque con PostgreSQL seleccionado
- **WHEN** bootstrap indica un PostgreSQL remoto como backend activo
- **THEN** todos los procesos descubren ese backend a través del SQLite local y no necesitan una URL externa

### Requirement: SQLite local de fallback separado
Toda instalación SHALL disponer de un almacén SQLite de fallback separado del bootstrap. SHALL conservar solo la última instantánea válida necesaria para control seguro, el plan ejecutable, estado operativo mínimo, metadatos de frescura y una outbox duradera de eventos producidos sin conectividad.

#### Scenario: Actualización de la réplica mínima
- **WHEN** el backend canónico confirma una nueva configuración o un nuevo plan apto para ejecución
- **THEN** el fallback reemplaza atómicamente su instantánea y registra la revisión y el instante de sincronización

#### Scenario: Datos excluidos del fallback
- **WHEN** se examina el almacén de fallback
- **THEN** no contiene una copia editable completa del histórico ni datos ajenos a continuidad, diagnóstico o reconciliación pendiente

### Requirement: Separación física compatible con cada driver
En PostgreSQL, configuración y aplicación SHALL residir en namespaces independientes del mismo destino canónico. En SQLite, los cuatro almacenes lógicos SHALL materializarse en ficheros o bases de datos independientes de modo que bootstrap y fallback nunca compartan el ciclo de migración del backend activo.

#### Scenario: SQLite como driver activo
- **WHEN** se elige SQLite para funcionamiento canónico
- **THEN** bootstrap, fallback, configuración y aplicación siguen siendo identificables, versionables y recuperables por separado

#### Scenario: PostgreSQL como driver activo
- **WHEN** se elige PostgreSQL remoto
- **THEN** la configuración completa y todos los datos de aplicación/runtime canónicos residen en PostgreSQL y SQLite conserva únicamente bootstrap y fallback

### Requirement: Conmutación transaccional del driver
El sistema SHALL tratar un cambio de driver como una operación explícita y exclusiva: comprobar conectividad y permisos, preparar ambos esquemas, copiar configuración y datos de aplicación, verificar recuentos e integridad, y cambiar el locator de bootstrap solo tras completar todas las verificaciones.

#### Scenario: Migración correcta a PostgreSQL
- **WHEN** el destino supera el preflight y todos los datos se copian y verifican
- **THEN** bootstrap conmuta a PostgreSQL, los procesos reabren el backend nuevo y este pasa a ser la única fuente canónica

#### Scenario: Fallo antes de la conmutación
- **WHEN** falla conexión, migración, copia o verificación
- **THEN** el backend original continúa activo e íntegro, el destino incompleto no se usa y el operador recibe la fase y causa del fallo sin secretos

#### Scenario: Conmutación solicitada mientras hay otra activa
- **WHEN** ya hay una migración o conmutación en curso
- **THEN** la nueva solicitud se rechaza sin iniciar trabajo concurrente

### Requirement: El backend canónico remoto tiene autoridad única
Cuando PostgreSQL está seleccionado, SHALL ser la autoridad de configuración y aplicación. El sistema MUST NOT aceptar ediciones administrativas contra la copia de fallback ni mezclar automáticamente configuraciones divergentes.

#### Scenario: Edición durante pérdida de red
- **WHEN** PostgreSQL no está disponible y el sistema opera desde fallback
- **THEN** la lectura identifica la instantánea y su antigüedad, y toda mutación administrativa se rechaza como temporalmente no disponible

### Requirement: Continuidad segura sin PostgreSQL
Si el backend remoto deja de responder, el controlador SHALL continuar con la última configuración y plan local que sean válidos y suficientemente recientes. Si no existe evidencia segura, SHALL apagar todas las salidas y permanecer vivo en estado degradado.

#### Scenario: Corte con plan válido
- **WHEN** se pierde PostgreSQL mientras existe un plan fallback vigente
- **THEN** el controlador mantiene su ejecución, registra una única transición a degradado y no depende de nuevas lecturas remotas para conmutar las salidas previstas

#### Scenario: Corte sin plan seguro
- **WHEN** PostgreSQL no responde y falta un plan válido o su validez ha expirado
- **THEN** todas las salidas quedan apagadas y el diagnóstico explica por qué no se usa el fallback

### Requirement: Escrituras runtime offline se reconcilian de forma idempotente
Los eventos runtime esenciales generados durante un corte SHALL escribirse primero en una outbox local duradera con identificador estable, orden causal y estado de entrega. Al recuperar PostgreSQL SHALL reproducirse sin duplicados y solo se eliminarán localmente después de confirmación remota.

#### Scenario: Recuperación después de acumular eventos
- **WHEN** vuelve la conectividad y existen eventos pendientes
- **THEN** se envían en orden compatible con sus dependencias, cada evento aparece una sola vez en el backend canónico y el contador pendiente llega a cero tras confirmarse

#### Scenario: Nueva caída durante la reconciliación
- **WHEN** se interrumpe la red después de confirmar algunos eventos
- **THEN** la siguiente recuperación continúa desde los no confirmados sin duplicar los ya aplicados

### Requirement: Recuperación remota refresca el estado local
Tras recuperar el backend remoto, el sistema SHALL verificar su versión, completar la outbox, releer la configuración canónica y refrescar la instantánea de fallback antes de abandonar el estado degradado.

#### Scenario: PostgreSQL vuelve con configuración más reciente
- **WHEN** el backend vuelve a estar disponible y contiene una revisión posterior a la réplica local
- **THEN** el sistema adopta la revisión remota, actualiza el fallback y solo entonces declara estado normal

### Requirement: Topología y frescura observables
El sistema SHALL exponer el driver canónico, estado de conexión, modo normal/bootstrap/fallback/migrando, revisión y edad de la instantánea local, eventos pendientes y última reconciliación, sin revelar URLs con credenciales.

#### Scenario: Diagnóstico en modo degradado
- **WHEN** un operador consulta salud durante un corte
- **THEN** distingue indisponibilidad remota de fallo total y obtiene antigüedad del fallback y cantidad de eventos pendientes

### Requirement: Fallos del bootstrap producen estado seguro
Un bootstrap ausente se puede crear únicamente como primera instalación; uno corrupto, incompatible o ambiguo MUST NOT reemplazarse ni ignorarse automáticamente. Los procesos que controlan salidas SHALL quedar en estado seguro y el sistema SHALL ofrecer un procedimiento explícito de recuperación.

#### Scenario: Bootstrap incompatible
- **WHEN** el servicio encuentra una versión más nueva o datos inconsistentes en bootstrap
- **THEN** no abre otro backend por suposición, no activa salidas y reporta la incompatibilidad sin destruir el almacén existente

