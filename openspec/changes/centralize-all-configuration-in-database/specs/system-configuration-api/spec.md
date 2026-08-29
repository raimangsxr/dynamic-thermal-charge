## Purpose

Define la superficie administrativa para completar el onboarding, gestionar toda la configuración persistente y controlar migraciones de backend sin exponer secretos.

## ADDED Requirements

### Requirement: Onboarding autenticado de un solo uso
Una instalación no configurada SHALL ofrecer únicamente salud y operaciones de onboarding. El sistema SHALL generar una credencial de bootstrap de un solo uso, comunicarla una vez por un canal local al crear la instalación y exigirla para establecer la credencial administrativa definitiva.

#### Scenario: Primera configuración autorizada
- **WHEN** el usuario presenta la credencial de bootstrap vigente y una credencial administrativa válida
- **THEN** el sistema guarda la credencial definitiva, invalida irreversiblemente la de bootstrap y habilita la API administrativa

#### Scenario: Reutilización o acceso anónimo
- **WHEN** falta la credencial de bootstrap o se intenta reutilizar después del onboarding
- **THEN** la operación se rechaza sin revelar el estado de otras credenciales ni datos de configuración

### Requirement: Contrato completo de configuración de sistema
La API SHALL permitir leer y actualizar por secciones toda la configuración persistente, incluyendo base de datos, API, MQTT, weather, outputs, logging y operación. Cada respuesta SHALL incluir revisión, validaciones aplicables, semántica de activación y estado de secretos.

#### Scenario: Lectura administrativa
- **WHEN** un administrador autenticado consulta una sección
- **THEN** recibe valores no secretos, indicadores de secretos, revisión y si algún cambio o reinicio está pendiente

#### Scenario: Actualización parcial válida
- **WHEN** el administrador actualiza una sección con su revisión vigente
- **THEN** la API valida la configuración global, confirma atómicamente y devuelve la nueva revisión sin secretos

### Requirement: Secretos con semántica explícita
Los campos secretos SHALL aceptar las operaciones conservar, reemplazar y borrar cuando el campo sea opcional. Omitir un secreto SHALL conservarlo; ningún placeholder visual SHALL interpretarse como valor nuevo.

#### Scenario: Guardar otros campos sin tocar la contraseña
- **WHEN** una petición omite una contraseña ya configurada
- **THEN** la contraseña se conserva y la respuesta solo indica que sigue configurada

#### Scenario: Borrar una credencial obligatoria
- **WHEN** se solicita borrar un secreto requerido por la configuración resultante
- **THEN** la operación completa se rechaza y el valor anterior se conserva

### Requirement: Prueba previa de integraciones
La API SHALL permitir comprobar, sin persistir, la conexión a PostgreSQL, MQTT y proveedores externos usando los valores candidatos y SHALL devolver resultados sanitizados y acotados por timeout.

#### Scenario: Prueba correcta
- **WHEN** el administrador prueba valores candidatos válidos
- **THEN** recibe confirmación de conectividad y capacidades requeridas sin que los valores queden guardados ni aparezcan en logs

#### Scenario: Prueba fallida
- **WHEN** el destino rechaza credenciales o no responde
- **THEN** la API distingue la categoría de fallo, no devuelve el secreto y termina dentro del límite de tiempo

### Requirement: Migración de backend como operación observable
La API SHALL iniciar la conmutación con confirmación explícita, devolver un identificador de operación y permitir consultar fase, progreso, resultado y diagnóstico sanitizado. Mientras la operación sea crítica SHALL bloquear cambios incompatibles.

#### Scenario: Seguimiento de migración
- **WHEN** un administrador inicia una migración a PostgreSQL válida
- **THEN** puede seguir preflight, preparación, copia, verificación y conmutación hasta un resultado terminal

#### Scenario: Error de migración
- **WHEN** una fase falla
- **THEN** el resultado indica que el backend anterior sigue activo y qué acción puede tomar el operador

### Requirement: Administración no disponible en fallback
Cuando el sistema opera desde fallback, la API SHALL mantener disponibles salud, estado y lectura sanitizada de la última configuración, pero SHALL rechazar mutaciones, pruebas que dependan del backend canónico y nuevas migraciones con un error temporal y reintentable.

#### Scenario: Intento de edición offline
- **WHEN** un administrador guarda cambios mientras PostgreSQL está inaccesible
- **THEN** recibe un error de modo degradado, no cambia el fallback y puede consultar su antigüedad y el estado de reconexión

### Requirement: Autenticación y rotación resisten cambios de backend
La autenticación SHALL resolverse desde el almacén disponible apropiado sin crear una ventana anónima durante arranque, migración o fallback. La copia local necesaria para verificar acceso en fallback SHALL ser no reversible y SHALL actualizarse al rotar la credencial.

#### Scenario: API durante caída remota
- **WHEN** PostgreSQL cae después de una autenticación configurada
- **THEN** el administrador válido aún puede consultar diagnóstico, un token incorrecto sigue rechazado y ninguna credencial en claro reside en fallback

### Requirement: Auditoría de cambios y operaciones sensibles
El sistema SHALL registrar quién o qué cliente solicitó un cambio, la sección y campos afectados, revisión anterior y nueva, resultado y timestamps, sin registrar valores secretos. Onboarding, rotaciones y migraciones SHALL quedar auditados.

#### Scenario: Rotación de API key
- **WHEN** se reemplaza una API key correctamente
- **THEN** la auditoría identifica el campo como rotado y el resultado, pero no el valor anterior ni el nuevo

### Requirement: Compatibilidad de concurrencia y errores
La API SHALL usar conflictos de revisión para ediciones concurrentes y errores estructurados para validación, indisponibilidad, autenticación y operaciones en curso. MUST NOT devolver trazas, URLs con contraseña ni excepciones del driver.

#### Scenario: Dos clientes editan la misma revisión
- **WHEN** el segundo cliente guarda después de que el primero haya confirmado
- **THEN** recibe un conflicto con la revisión vigente y ninguna parte de su propuesta se aplica

