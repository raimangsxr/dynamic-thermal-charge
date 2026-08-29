## Purpose

Define la experiencia frontend para inicializar el sistema y administrar de forma segura toda su configuración, topología de datos y estado de continuidad.

## ADDED Requirements

### Requirement: Sección diferenciada de Configuración del sistema
El frontend SHALL incorporar una ruta y entrada de navegación «Configuración del sistema» separada de la configuración funcional de instalación y acumuladores. SHALL agrupar base de datos, API y seguridad, MQTT, weather, outputs, logging y operación en secciones comprensibles.

#### Scenario: Navegación autenticada
- **WHEN** un usuario autenticado abre Configuración del sistema
- **THEN** ve un resumen del estado y puede acceder a cada grupo sin mezclarlo con la edición de acumuladores

### Requirement: Asistente de primera puesta en marcha
Cuando el backend indique que la instalación no está configurada, el frontend SHALL mostrar un asistente que solicite la credencial de bootstrap, permita crear la credencial administrativa y guíe por los mínimos necesarios para alcanzar un sistema operativo.

#### Scenario: Instalación nueva
- **WHEN** se abre el frontend de una instalación sin onboarding
- **THEN** se bloquean las pantallas operativas, se explica dónde obtener la credencial de un solo uso y se muestran los pasos pendientes

#### Scenario: Finalización del onboarding
- **WHEN** se completan y validan los pasos obligatorios
- **THEN** el usuario entra en la aplicación autenticada y la credencial de bootstrap deja de ofrecerse

### Requirement: Formularios seguros y conscientes de revisión
Los formularios SHALL mostrar validación por campo y global, conservar la revisión leída y manejar conflictos sin sobrescribir cambios ajenos. SHALL indicar qué ajustes se aplican en caliente, en próximo ciclo o requieren reinicio.

#### Scenario: Conflicto al guardar
- **WHEN** otro cliente modifica la configuración antes del guardado
- **THEN** el frontend conserva la edición local, muestra el conflicto y permite recargar o comparar sin reenviarla automáticamente

#### Scenario: Reinicio pendiente
- **WHEN** se guarda un ajuste que requiere reinicio
- **THEN** la interfaz identifica el proceso afectado y mantiene el aviso hasta que el backend confirme que usa la nueva revisión

### Requirement: Tratamiento de secretos sin reexposición
Los campos secretos SHALL aparecer vacíos con indicador configurado/no configurado y acciones explícitas de reemplazo o borrado. El frontend MUST NOT recuperar, insertar en el DOM, persistir en almacenamiento del navegador ni registrar un secreto existente.

#### Scenario: Editar una sección con secreto existente
- **WHEN** el usuario cambia un campo no secreto y guarda sin reemplazar la credencial
- **THEN** el secreto se conserva y ningún placeholder se envía como valor

#### Scenario: Error tras introducir un secreto
- **WHEN** falla la validación o la conexión
- **THEN** el secreto no aparece en el mensaje, URL, telemetría ni estado persistido del navegador

### Requirement: Flujo guiado de selección y migración de base de datos
La interfaz SHALL permitir elegir SQLite o PostgreSQL, probar la conexión candidata y revisar el alcance antes de migrar. SHALL requerir confirmación explícita, mostrar progreso por fases y no declarar éxito hasta que el backend nuevo esté activo y verificado.

#### Scenario: Migración exitosa
- **WHEN** el usuario confirma una migración a PostgreSQL y finaliza correctamente
- **THEN** la interfaz muestra PostgreSQL como canónico, la última sincronización local y que configuración y aplicación fueron verificadas

#### Scenario: Migración fallida
- **WHEN** la operación termina con error
- **THEN** la interfaz afirma que el driver anterior sigue activo, muestra un diagnóstico sanitizado y permite corregir y reintentar

### Requirement: Estado de almacenamiento visible
La sección SHALL mostrar driver canónico, modo normal/bootstrap/fallback/migrando, conectividad, frescura del fallback, última reconciliación y eventos pendientes. Un estado degradado SHALL ser visible también desde el shell general.

#### Scenario: Corte de PostgreSQL
- **WHEN** el frontend recibe estado fallback
- **THEN** muestra una advertencia persistente con antigüedad y cola pendiente, mantiene las lecturas disponibles y deshabilita acciones administrativas explicando el motivo

### Requirement: Confirmaciones proporcionales al riesgo
Rotar autenticación, borrar secretos, cambiar driver y modificar el output real SHALL requerir una confirmación que describa el efecto. La interfaz MUST NOT combinar estos actos con un guardado genérico ambiguo.

#### Scenario: Cambio a output real
- **WHEN** el usuario intenta pasar del driver simulado al real
- **THEN** la interfaz resume el hardware afectado y exige confirmación separada antes de enviar el cambio

### Requirement: Accesibilidad y estados completos
Todos los formularios, banners, diálogos y progresos SHALL ser utilizables por teclado, tener foco visible, etiquetas y anuncios accesibles, y no depender solo del color. SHALL representar carga, vacío, éxito, validación, conflicto, indisponibilidad y error inesperado.

#### Scenario: Operación larga con lector de pantalla
- **WHEN** cambia la fase de una migración
- **THEN** el progreso se anuncia sin mover el foco de forma inesperada y el usuario puede consultar el detalle con teclado

