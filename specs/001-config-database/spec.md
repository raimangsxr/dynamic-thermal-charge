# Feature Specification: Configuración y histórico en base de datos

**Feature Branch**: `001-config-database`

**Created**: 2026-08-26

**Status**: Draft

**Input**: User description: "Sustituir la configuración estática en YAML por persistencia en base de datos, configurable entre SQLite local y PostgreSQL remoto. Corte limpio con YAML, semilla por defecto, histórico de planes y transiciones con retención configurable, cadena de conexión en variable de entorno."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Arrancar el servicio con la configuración en base de datos (Priority: P1)

Quien opera la instalación indica al servicio dónde está su base de datos mediante una
variable de entorno. Al arrancar, el servicio obtiene de ahí la instalación completa
—límite de potencia, ventana de carga, proveedor meteorológico, parámetros de ejecución y
la lista de acumuladores con su perfil térmico y su salida— y planifica exactamente igual
que planificaba leyendo un fichero. No existe ningún fichero de configuración de
instalación en el sistema.

**Why this priority**: Es la sustitución completa del mecanismo de configuración. Sin ella
no hay nada que las fases posteriores (API, interfaz web, Home Assistant) puedan leer ni
escribir, y el servicio no arranca.

**Independent Test**: Con una base de datos local ya sembrada y la variable de entorno
apuntando a ella, se ejecuta el planificador y se comprueba que el plan generado es
idéntico al que producía la configuración equivalente en fichero.

**Acceptance Scenarios**:

1. **Given** una base de datos local con una instalación válida sembrada, **When** se
   arranca el planificador sin indicar ningún fichero de configuración, **Then** se genera
   el plan de carga esperado y el log registra el origen de la configuración sin revelar
   credenciales.
2. **Given** la misma instalación almacenada en una base de datos remota en lugar de local,
   **When** se arranca el planificador, **Then** el plan generado es idéntico al del caso
   local.
3. **Given** que no se ha indicado ninguna ubicación de base de datos, **When** se arranca
   cualquier modo de ejecución, **Then** el proceso termina con un error que explica qué
   variable falta y cómo definirla, y ninguna salida se activa.
4. **Given** una instalación almacenada con un dato inválido, por ejemplo dos acumuladores
   con el mismo identificador, **When** se arranca el servicio, **Then** el arranque falla
   con un mensaje que identifica el campo y el acumulador ofensores, y ninguna salida se
   activa.

---

### User Story 2 - Inicializar una instalación nueva desde cero (Priority: P1)

Quien instala el servicio por primera vez, o lo actualiza desde una versión basada en
ficheros, prepara la base de datos con un único comando. El comando crea el esquema y,
si la instalación está vacía, siembra una instalación de ejemplo completa y válida que
sirve como punto de partida y como documentación viva de los campos disponibles. Un
segundo comando muestra la configuración vigente en un formato legible para poder
revisarla y compararla con la que se quiere conseguir.

**Why this priority**: Sin inicialización no hay forma de llegar al escenario de la
historia 1, y la inspección es la forma de verificar el estado real de la instalación antes
y después de cada cambio de la historia 3.

**Independent Test**: Sobre una base de datos vacía se ejecuta la inicialización y después
la inspección, y se comprueba que lo mostrado es una instalación completa, válida y
suficiente para arrancar el planificador.

**Acceptance Scenarios**:

1. **Given** una base de datos vacía, **When** se ejecuta la inicialización, **Then** se
   crea el esquema, se siembra una instalación de ejemplo válida y se informa de qué se ha
   creado.
2. **Given** una base de datos ya inicializada con configuración propia, **When** se
   vuelve a ejecutar la inicialización, **Then** el esquema se actualiza si hace falta, la
   configuración existente no se modifica ni se sobrescribe con la semilla, y se informa de
   que la siembra se ha omitido.
3. **Given** una instalación cualquiera almacenada, **When** se ejecuta el comando de
   inspección, **Then** se muestran todos los parámetros de la instalación y de cada
   acumulador, sin mostrar en ningún caso credenciales ni la cadena de conexión completa.
4. **Given** una base de datos creada por una versión anterior del esquema, **When** se
   ejecuta la inicialización, **Then** las migraciones pendientes se aplican en orden y los
   datos existentes se conservan.

---

### User Story 3 - Editar la configuración sin salir de la línea de comandos (Priority: P1)

Quien opera la instalación ajusta la configuración almacenada con un comando, sin escribir
sentencias de base de datos a mano y sin necesitar la interfaz web todavía. Puede cambiar
un parámetro de la instalación, un parámetro de un acumulador concreto, habilitar o
deshabilitar un acumulador, y añadir o eliminar acumuladores. Cada cambio se valida contra
la configuración completa resultante antes de aplicarse: si el resultado sería inválido, no
se aplica nada y el error dice qué campo lo impide.

**Why this priority**: Sin edición asistida, la única forma de partir de la instalación
sembrada y llegar a la instalación real es escribir SQL a mano contra el almacén, lo que
esquiva por completo la validación y permite dejar la base de datos en un estado que el
servicio rechazará al arrancar. Es la contrapartida necesaria de haber eliminado los
ficheros de configuración.

**Independent Test**: Sobre una instalación sembrada se aplican cambios válidos e inválidos
mediante el comando, y se comprueba con el comando de inspección qué quedó almacenado y qué
se rechazó.

**Acceptance Scenarios**:

1. **Given** una instalación almacenada válida, **When** se modifica un parámetro de la
   instalación a un valor válido, **Then** el cambio queda almacenado, el comando informa
   del valor anterior y del nuevo, y la inspección refleja el valor nuevo.
2. **Given** una instalación almacenada válida, **When** se modifica un parámetro de un
   acumulador concreto a un valor válido, **Then** solo ese acumulador cambia y el resto de
   la configuración permanece intacta.
3. **Given** una instalación almacenada válida, **When** se intenta un cambio que dejaría la
   configuración global inválida —por ejemplo una resolución de intervalo que desalinea el
   horario ya configurado, o una salida física ya usada por otro acumulador—, **Then** no se
   aplica ningún cambio, el almacén queda exactamente como estaba y el error identifica el
   campo y el conflicto.
4. **Given** una instalación almacenada, **When** se intenta modificar un campo inexistente
   o un acumulador inexistente, **Then** el comando falla indicando los nombres admitidos o
   los acumuladores existentes, y no modifica nada.
5. **Given** una instalación almacenada, **When** se añade un acumulador nuevo con todos sus
   datos obligatorios, **Then** queda almacenado y la configuración resultante sigue siendo
   válida; **When** se elimina un acumulador, **Then** desaparece junto con su salida y su
   perfil térmico, y su histórico previo se conserva.
6. **Given** un servicio en marcha, **When** se edita la configuración, **Then** el plan en
   curso no se altera y el cambio se aplica en el siguiente recálculo del plan.
7. **Given** un intento de escribir un secreto —una credencial o una cadena de conexión— en
   un campo de configuración, **Then** el comando lo rechaza indicando que los secretos se
   sirven por variable de entorno.

---

### User Story 4 - Auditar qué pasó una noche concreta (Priority: P2)

Quien opera la instalación quiere saber por qué un acumulador cargó o no cargó una noche
determinada. La base de datos conserva los planes generados, las previsiones
meteorológicas que se usaron para calcularlos —incluyendo si vinieron del proveedor real o
del valor de reserva— y cada transición de encendido y apagado de cada salida con su
instante. Con eso se puede reconstruir la noche completa sin depender de los logs del
sistema.

**Why this priority**: Es lo que da contenido real a la interfaz web y a la integración
domótica posteriores, y hace auditable el comportamiento del sistema. No obstante, el
servicio puede planificar y conmutar correctamente sin el histórico, por lo que va después
de las dos primeras historias.

**Independent Test**: Se ejecuta el controlador contra un plan conocido con reloj
controlado, y después se consulta el histórico almacenado para comprobar que contiene el
plan, la previsión usada y la secuencia exacta de transiciones.

**Acceptance Scenarios**:

1. **Given** un servicio en marcha que genera un plan, **When** el plan se calcula,
   **Then** queda registrado con su instante de creación, su ventana, sus intervalos por
   acumulador y la previsión meteorológica utilizada.
2. **Given** una previsión obtenida del valor de reserva porque el proveedor real falló,
   **When** se consulta el histórico, **Then** la previsión registrada indica que su origen
   fue el valor de reserva.
3. **Given** un controlador que enciende y apaga salidas, **When** una salida cambia de
   estado, **Then** el histórico recoge el identificador del acumulador, el estado nuevo y
   el instante del cambio, y no recoge nada cuando el estado no cambia.
4. **Given** un plan que no puede cubrir toda la carga solicitada, **When** se consulta el
   histórico de ese plan, **Then** los minutos no atendidos de cada acumulador quedan
   registrados como parte del plan.

---

### User Story 5 - Evitar que el histórico agote el almacenamiento (Priority: P2)

Quien opera la instalación define cuánto tiempo se conserva el histórico. El servicio
elimina periódicamente los registros más antiguos que ese límite, de forma que un
dispositivo con almacenamiento reducido pueda funcionar durante años sin intervención
manual. La configuración vigente y el plan activo nunca se ven afectados por esta limpieza.

**Why this priority**: El destino de despliegue es un dispositivo con tarjeta de memoria
como único almacenamiento; un histórico sin límite lo agota y deja el servicio inoperativo.
Depende de que exista el histórico de la historia 3.

**Independent Test**: Con un histórico sembrado que abarca un periodo mayor que la
retención configurada y un reloj controlado, se dispara la limpieza y se comprueba qué
registros sobreviven.

**Acceptance Scenarios**:

1. **Given** una retención configurada y un histórico con registros más antiguos que ese
   límite, **When** se ejecuta la limpieza, **Then** los registros anteriores al límite se
   eliminan, los posteriores se conservan y se registra cuántos se han eliminado.
2. **Given** el plan actualmente en ejecución, **When** se ejecuta la limpieza, **Then** el
   plan activo y la configuración de la instalación se conservan íntegros aunque su
   antigüedad supere la retención.
3. **Given** una retención configurada como ilimitada, **When** se ejecuta la limpieza,
   **Then** no se elimina ningún registro.

---

### User Story 6 - Sobrevivir a una base de datos que falla (Priority: P1)

La base de datos puede estar remota y la red puede caerse. Cuando el servicio ya está en
marcha y pierde el acceso a la base de datos, mantiene en ejecución el plan que ya tiene y
reintenta según la cadencia configurada, sin terminar el proceso y sin dejar salidas en un
estado indeterminado. Cuando no hay ningún plan válido que ejecutar, todas las salidas
quedan apagadas.

**Why this priority**: El estado seguro es un principio no negociable del proyecto y una
base de datos remota introduce un modo de fallo que hoy no existe. Debe quedar cubierto en
la misma fase que introduce la dependencia.

**Independent Test**: Se inyecta un acceso a base de datos que falla de forma controlada
durante la ejecución y se observa el estado de las salidas y la continuidad del proceso.

**Acceptance Scenarios**:

1. **Given** un servicio en marcha con un plan válido, **When** la base de datos deja de
   responder, **Then** el plan en curso se sigue ejecutando, el fallo se registra una sola
   vez al entrar en estado degradado y el proceso no termina.
2. **Given** un servicio en estado degradado, **When** la base de datos vuelve a responder,
   **Then** la recuperación se registra y el plan se recalcula con la configuración vigente.
3. **Given** un arranque en el que la base de datos no responde, **When** no hay ningún
   plan válido disponible, **Then** todas las salidas quedan apagadas y el proceso informa
   del fallo sin activar nada.
4. **Given** un fallo al escribir un registro de histórico, **When** el servicio continúa,
   **Then** el error se registra y ni la planificación ni la conmutación de salidas se
   interrumpen.

---

### Edge Cases

- La cadena de conexión indica una base de datos remota inalcanzable durante el arranque:
  el proceso informa del fallo, no activa ninguna salida y no deja el esquema a medias.
- La cadena de conexión apunta a un motor no soportado: se rechaza al arrancar con un
  mensaje que enumera los motores admitidos.
- La ruta de la base de datos local está en un directorio inexistente o sin permiso de
  escritura: el error identifica la ruta y el permiso que falta.
- El almacenamiento se llena durante una escritura de histórico: el registro se pierde con
  un error registrado, pero el plan activo y el estado de las salidas no se corrompen.
- Dos procesos escriben a la vez en la misma base de datos local: las escrituras se
  serializan y ningún lector observa un registro a medias.
- Dos procesos escriben a la vez la copia local del plan activo: ningún lector observa un
  plan a medias, porque el reemplazo es atómico. La última escritura gana y la anterior se
  pierde sin aviso, lo que es aceptable porque ambas provienen del mismo plan vigente; lo
  que NO es aceptable es un plan truncado o mezclado.
- La configuración vigente cambia mientras hay un plan en ejecución: el plan en curso se
  mantiene hasta el siguiente recálculo, y el histórico permite saber con qué configuración
  se generó cada plan.
- La instalación almacenada no tiene ningún acumulador habilitado: la configuración se
  acepta y el plan resultante está vacío, con todas las salidas apagadas.
- El límite de retención se reduce drásticamente: la primera limpieza posterior elimina un
  volumen grande de registros de una vez sin bloquear la planificación.
- La base de datos contiene un esquema de una versión posterior a la del servicio: el
  arranque se rechaza en lugar de operar sobre datos que no comprende.
- Una edición se interrumpe a mitad —proceso terminado, red caída con base de datos
  remota—: el almacén queda con la configuración anterior íntegra, nunca a medias.
- Se elimina el último acumulador de la instalación: la operación se acepta y la
  configuración resultante es válida, con un plan vacío y todas las salidas apagadas.
- Se edita la configuración desde dos procesos a la vez: la segunda escritura no pierde
  silenciosamente la primera; el conflicto se detecta o las escrituras se serializan.

## Requirements *(mandatory)*

### Functional Requirements

> **Nota de orden**: los bloques no siguen numeración corrida. El bloque de edición
> (FR-032 a FR-040) se añadió tras FR-015 al ampliar el alcance de la fase, y se colocó en
> su lugar lógico en lugar de renumerar el resto, para no invalidar las referencias ya
> escritas en `plan.md`, `tasks.md` y los contratos. El orden de lectura es:
> FR-001–FR-015, FR-032–FR-040, FR-016–FR-031.

**Origen y arranque de la configuración**

- **FR-001**: El sistema MUST obtener la configuración completa de la instalación de una
  base de datos, y MUST NOT leer ningún fichero de configuración de instalación en el
  runtime.
- **FR-002**: El sistema MUST admitir tanto una base de datos local en el propio
  dispositivo como una base de datos remota, seleccionable sin cambiar código ni
  reinstalar, y MUST comportarse de forma idéntica en ambas.
- **FR-003**: El sistema MUST obtener la ubicación y las credenciales de la base de datos
  de una variable de entorno nombrada, y MUST NOT almacenarlas en el repositorio, en la
  propia base de datos ni en los logs.
- **FR-004**: El sistema MUST fallar el arranque con un mensaje accionable cuando esa
  variable de entorno no esté definida, esté vacía o indique un motor no soportado, y
  MUST NOT activar ninguna salida en ese caso.
- **FR-005**: El sistema MUST registrar al arrancar el origen efectivo de la configuración
  de forma que se distinga base de datos local de remota, MUST NOT incluir credenciales en
  ese registro.
- **FR-006**: El sistema MUST eliminar del runtime la carga de configuración basada en
  ficheros, incluidos su validación y sus opciones de línea de comandos asociadas.

**Validación e integridad de la configuración**

- **FR-007**: El sistema MUST validar íntegramente la configuración al cargarla y MUST
  rechazarla completa cuando cualquier campo sea inválido; MUST NOT aplicar una
  configuración parcialmente válida.
- **FR-008**: Cada error de validación MUST identificar el campo ofensor y, cuando
  corresponda, el acumulador al que pertenece, con un mensaje que permita corregirlo sin
  consultar el código.
- **FR-009**: El sistema MUST conservar todos los invariantes de la configuración vigentes
  hoy: identificadores de acumulador únicos, asignaciones de salida física únicas y dentro
  del rango admitido, resolución de intervalo divisora de una hora, ventana de carga
  múltiplo de la resolución de intervalo, horarios de inicio y fin alineados con la
  resolución de intervalo, potencia y tiempos de carga positivos, fracción de carga
  solicitada entre cero y uno, límites de carga del perfil térmico ordenados entre cero y
  uno, temperatura exterior de diseño inferior a la temperatura objetivo, y presencia de
  proveedor meteorológico cuando algún acumulador tiene perfil térmico.
- **FR-010**: El sistema MUST rechazar el arranque cuando la versión del esquema de la
  base de datos sea posterior a la que el servicio comprende, y MUST NOT activar ninguna
  salida en ese caso.

**Inicialización e inspección**

- **FR-011**: El sistema MUST ofrecer una operación que cree el esquema en una base de
  datos vacía y aplique en orden las migraciones pendientes en una base de datos existente,
  conservando los datos ya almacenados.
- **FR-012**: El sistema MUST sembrar una instalación de ejemplo completa y válida cuando
  la base de datos no contenga ninguna configuración, y MUST NOT modificar ni sobrescribir
  una configuración ya existente.
- **FR-013**: La operación de inicialización MUST ser repetible sin efectos adversos y
  MUST informar de qué ha creado, qué ha migrado y qué ha omitido.
- **FR-014**: El sistema MUST ofrecer una operación de solo lectura que muestre la
  configuración vigente completa en un formato legible, incluyendo la versión del esquema,
  y MUST NOT revelar credenciales ni la cadena de conexión completa.
- **FR-015**: El sistema MUST NOT exponer ninguna interfaz de red en esta fase; la API y
  la interfaz web corresponden a fases posteriores.

**Edición de la configuración**

- **FR-032**: El sistema MUST ofrecer una operación de línea de comandos que modifique un
  parámetro de la instalación o de un acumulador concreto, identificando el campo por su
  nombre y el acumulador por su identificador.
- **FR-033**: El sistema MUST ofrecer operaciones de línea de comandos para añadir un
  acumulador nuevo con sus datos obligatorios y para eliminar un acumulador existente. La
  eliminación MUST arrastrar su salida y su perfil térmico, y MUST NOT eliminar su
  histórico.
- **FR-034**: Toda edición MUST validarse contra la configuración completa resultante antes
  de aplicarse, con los mismos invariantes de FR-009. Un resultado inválido MUST dejar el
  almacén exactamente como estaba y MUST NOT aplicar cambios parciales.
- **FR-035**: Cada edición MUST ser atómica y durable: una interrupción a mitad de la
  operación MUST dejar la configuración anterior íntegra.
- **FR-036**: Cada edición aplicada MUST informar del campo modificado, su valor anterior y
  su valor nuevo, y MUST quedar registrada con su instante para poder auditar quién cambió
  qué y cuándo.
- **FR-037**: Un campo o un acumulador inexistente MUST producir un error que enumere los
  nombres de campo admitidos o los acumuladores existentes, sin modificar nada.
- **FR-038**: El sistema MUST rechazar el almacenamiento de credenciales o cadenas de
  conexión en cualquier campo de configuración, indicando que los secretos se sirven por
  variable de entorno (FR-003).
- **FR-039**: Una edición MUST NOT alterar el plan en ejecución; el cambio MUST tomar
  efecto en el siguiente recálculo del plan.
- **FR-040**: La edición concurrente desde dos procesos MUST NOT perder silenciosamente una
  de las escrituras: el conflicto se detecta o las escrituras se serializan.

**Histórico**

- **FR-016**: El sistema MUST registrar cada plan generado con su instante de creación, su
  ventana de carga, los intervalos asignados a cada acumulador y los minutos solicitados no
  atendidos de cada acumulador.
- **FR-017**: El sistema MUST registrar cada previsión meteorológica utilizada para generar
  un plan, incluyendo la fecha, las temperaturas empleadas y si su origen fue el proveedor
  configurado o el valor de reserva, y MUST poder asociarla al plan que la usó.
- **FR-018**: El sistema MUST registrar cada transición de estado de una salida con el
  identificador del acumulador, el estado resultante y el instante, y MUST NOT registrar
  nada cuando el estado no cambia.
- **FR-019**: Un fallo al escribir cualquier registro de histórico MUST registrarse como
  error y MUST NOT interrumpir la planificación, la conmutación de salidas ni el proceso.
- **FR-020**: El sistema MUST conservar el plan activo de forma que sobreviva a un reinicio
  y a un corte de alimentación sin quedar a medias, y MUST tratar un plan ilegible o de
  versión desconocida como ausencia de plan.

**Retención**

- **FR-021**: El sistema MUST permitir configurar cuánto tiempo se conserva el histórico,
  incluyendo la opción de conservarlo indefinidamente.
- **FR-022**: El sistema MUST eliminar periódicamente los registros de histórico anteriores
  al límite de retención e informar de cuántos ha eliminado.
- **FR-023**: La limpieza MUST NOT eliminar nunca la configuración de la instalación ni el
  plan activo, con independencia de su antigüedad.

**Estado seguro y continuidad**

- **FR-024**: Una base de datos inaccesible, vacía o con configuración inválida MUST NOT
  provocar la activación de ninguna salida ni dejar las salidas en un estado indeterminado.
- **FR-025**: La pérdida de acceso a la base de datos con el servicio ya en marcha MUST
  conservar el plan en ejecución y reintentar con la cadencia configurada, y MUST NOT
  terminar el proceso.
- **FR-026**: La entrada y la salida del estado degradado por fallo de base de datos MUST
  registrarse una sola vez en cada transición, y MUST NOT registrarse en cada iteración del
  bucle de control.
- **FR-027**: El planificador y el modelo térmico MUST seguir siendo deterministas y libres
  de acceso a datos; todo acceso a la base de datos MUST quedar detrás de una frontera
  sustituible en pruebas.
- **FR-028**: La suite de pruebas MUST poder ejecutarse completa sin una base de datos
  remota, sin red y sin hardware, y MUST cubrir explícitamente los caminos de fallo de base
  de datos descritos en FR-024 a FR-026.

**Despliegue**

- **FR-029**: El procedimiento de instalación y la unidad de servicio MUST proporcionar la
  ubicación de la base de datos por el mismo mecanismo protegido que ya sirve los secretos
  existentes, con permisos restringidos al usuario del servicio.
- **FR-030**: El procedimiento de instalación MUST dejar la base de datos inicializable con
  un único comando documentado, y MUST NOT arrancar el servicio automáticamente. Cuando
  detecte una instalación previa basada en ficheros, MUST NOT sembrar la instalación de
  ejemplo, para no interponer datos de ejemplo entre el operador y la configuración real que
  va a reintroducir (FR-031). El servicio no arranca sin configuración válida, por lo que
  una inicialización pendiente se manifiesta como servicio parado, nunca como salida
  activa.
- **FR-031**: La documentación MUST describir el procedimiento de actualización desde una
  versión basada en ficheros, advirtiendo de forma explícita que la configuración de la
  instalación debe reintroducirse manualmente porque no existe importación automática.

### Key Entities

- **Instalación**: la unidad de configuración completa de un emplazamiento. Agrupa el
  límite de potencia simultánea, la resolución de intervalo, la ventana de carga, el
  horario, el proveedor meteorológico con su reserva y su supervisión, los parámetros de
  ejecución, el nivel de registro y la política de retención. Contiene acumuladores.
- **Acumulador**: un aparato de carga térmica. Tiene identificador único dentro de la
  instalación, nombre, modelo opcional, potencia, tiempo de carga completa, fracción de
  carga solicitada, prioridad, estado de habilitación, una salida y, opcionalmente, un
  perfil térmico.
- **Salida**: la forma de accionar un acumulador. Tiene tipo, asignación física opcional y
  nivel activo. Su asignación física es única dentro de la instalación.
- **Perfil térmico**: los parámetros con los que se deriva la carga necesaria de un
  acumulador a partir de la temperatura exterior: temperatura objetivo, temperatura
  exterior de diseño, factor térmico y límites mínimo y máximo de carga.
- **Previsión**: las temperaturas usadas para calcular un plan, con su fecha, su origen
  —proveedor configurado o valor de reserva— y el instante en que se obtuvieron.
- **Plan**: el resultado de una planificación. Tiene instante de creación, ventana,
  configuración e instalación de origen, previsión asociada, los intervalos asignados a cada
  acumulador y los minutos solicitados no atendidos.
- **Intervalo de plan**: la asignación de un acumulador a un tramo de tiempo concreto
  dentro de un plan.
- **Transición de salida**: el cambio de estado de la salida de un acumulador, con su
  instante y el estado resultante.
- **Versión de esquema**: la revisión de estructura que la base de datos tiene aplicada,
  usada para decidir si migrar, operar o rechazar el arranque.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Ningún fichero de configuración de instalación queda en el sistema: el
  servicio arranca y planifica con la base de datos como única fuente de configuración.
- **SC-002**: Para una instalación equivalente, el plan generado desde base de datos local
  y desde base de datos remota es idéntico, y coincide con el que producía la configuración
  en fichero antes del cambio. La equivalencia con base de datos local se verifica en cada
  ejecución de la suite; la equivalencia entre motores se verifica de dos formas: una
  comprobación de que ambos dialectos generan sentencias equivalentes, que corre siempre y
  sin servidor, y una suite de extremo a extremo contra un servidor remoto real, que se
  ejecuta bajo demanda antes de un despliegue que use base de datos remota.
- **SC-003**: Una instalación nueva pasa de base de datos vacía a servicio capaz de
  planificar con una sola operación de inicialización y sin editar ficheros.
- **SC-011**: Un operador lleva la instalación sembrada a su configuración real completa
  —potencia, ventana, horario, proveedor meteorológico y todos sus acumuladores con pines y
  perfiles térmicos— usando solo comandos del propio servicio, sin escribir una sola
  sentencia de base de datos.
- **SC-012**: Ninguna secuencia de ediciones puede dejar el almacén en un estado que el
  servicio rechace al arrancar: toda edición que produciría esa situación se rechaza en el
  momento.
- **SC-004**: Un operador puede reconstruir por completo, a partir únicamente del
  histórico, por qué cada acumulador cargó o no cargó en una ventana concreta: plan,
  previsión utilizada, origen de la previsión, transiciones y minutos no atendidos.
- **SC-005**: Con la retención por defecto, el histórico de un año de funcionamiento
  continuo con cuatro acumuladores ocupa un volumen acotado y conocido, compatible con el
  almacenamiento del dispositivo de despliegue.
- **SC-006**: Ninguna condición de fallo de base de datos —ausente, inalcanzable, vacía,
  inválida, caída en caliente o llena— produce una salida activa que no esté respaldada por
  un plan válido.
- **SC-007**: Una caída de la base de datos durante la ejecución no termina el proceso: el
  plan en curso se completa y el servicio se recupera solo cuando la base de datos vuelve.
- **SC-008**: La suite completa de pruebas se ejecuta sin red, sin base de datos remota y
  sin hardware, y cubre cada camino de fallo de base de datos descrito.
- **SC-009**: Cada mensaje de error de configuración identifica el campo ofensor, de modo
  que un operador lo corrige sin leer código.
- **SC-010**: Actualizar el servicio no destruye ni el histórico ni la configuración
  almacenada: las migraciones de esquema se aplican conservando los datos.

## Assumptions

- La variable de entorno que transporta la ubicación de la base de datos se sirve por el
  mismo mecanismo protegido que ya usa el despliegue para la clave de la API
  meteorológica, con permisos restringidos al usuario del servicio.
- La base de datos remota es siempre externa al dispositivo de despliegue; no se contempla
  instalar un motor remoto en el propio dispositivo, cuyos recursos no lo permiten.
- En esta fase la configuración se modifica con los comandos del propio servicio sobre la
  instalación sembrada. El acceso directo al motor de base de datos deja de ser necesario y
  se considera fuera del camino soportado, porque esquiva la validación. La edición gráfica
  llega con la interfaz de las fases posteriores.
- La edición por línea de comandos cubre los campos existentes de la instalación y de los
  acumuladores. No se contempla en esta fase la edición interactiva, la edición por lotes
  desde un fichero, ni deshacer un cambio anterior.
- La instalación de ejemplo sembrada refleja el contenido de las configuraciones de ejemplo
  actuales del repositorio, que se conservan como documentación aunque el runtime ya no las
  lea.
- Los secretos siguen fuera de la base de datos: la clave de la API meteorológica se
  continúa leyendo de la variable de entorno nombrada en la configuración.
- La retención por defecto se fija en un valor conservador para el almacenamiento del
  dispositivo de despliegue, y es ajustable, incluyendo el valor ilimitado.
- El acceso concurrente esperado es de un único proceso de servicio más operaciones
  puntuales de inspección o mantenimiento. No se dimensiona para escritura concurrente
  intensiva.
- Una única instalación por base de datos en esta fase; el modelo no impide varias, pero
  soportarlas no forma parte del alcance.
- El histórico es un registro de auditoría de solo escritura y consulta: esta fase no
  incluye informes, agregaciones ni gráficas, que corresponden a la interfaz posterior.
- La constitución del proyecto fue enmendada a la versión 1.1.0 antes de la planificación
  de esta feature: el principio de configuración validada quedó expresado con independencia
  del origen de la configuración, y las restricciones de plataforma recogen ya el almacén de
  configuración en base de datos y sus dependencias.
