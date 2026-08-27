# Feature Specification: Integración con Home Assistant

**Feature Branch**: `004-home-assistant`

**Created**: 2026-08-27

**Status**: Draft

**Input**: User description: "Integración con Home Assistant por MQTT Discovery, con posibilidad de conectarse a HA por WireGuard. Home Assistant puede leer todo y cambiar dos cosas: habilitar un acumulador y su carga objetivo. Se consume de Home Assistant la temperatura interior real de cada estancia como entrada al modelo térmico, con reserva obligatoria. El publicador es un servicio propio."

## Clarifications

### Session 2026-08-27

- Q: ¿Cómo llegan al controlador las temperaturas recibidas por el publicador, si son procesos independientes? → A: El publicador guarda la última medida en la base de datos y el controlador la lee al recalcular el plan.
- Q: ¿Qué hace el publicador tras un rechazo de credenciales del broker? → A: Registra el rechazo una vez y reintenta cada 5 minutos.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ver la instalación en Home Assistant sin configurar nada (Priority: P1)

Quien usa Home Assistant conecta el servicio a su broker y las entidades aparecen solas: un
dispositivo por instalación y uno por acumulador, con su estado, su potencia, su plan y su
previsión. No hay que escribir configuración a mano en Home Assistant.

**Why this priority**: es la razón de ser de la fase. Sin descubrimiento automático, la
integración es un manual de instrucciones.

**Independent Test**: contra un broker de prueba, se arranca el servicio y se comprueba qué
mensajes de descubrimiento y de estado se publican, y en qué asuntos.

**Acceptance Scenarios**:

1. **Given** un broker accesible y una instalación con cuatro acumuladores, **When** arranca el
   servicio, **Then** se publica el descubrimiento de un dispositivo por instalación y uno por
   acumulador, con sus entidades.
2. **Given** el servicio en marcha, **Then** se publican periódicamente el estado de cada salida,
   la potencia instantánea y su porcentaje del límite, la ventana del plan en curso, la previsión
   con su origen, y los minutos solicitados, asignados y no atendidos por acumulador.
3. **Given** un acumulador que se añade a la configuración, **When** el servicio lo detecta,
   **Then** publica su descubrimiento sin necesidad de reiniciar Home Assistant.
4. **Given** un acumulador que se elimina de la configuración, **When** el servicio lo detecta,
   **Then** retira su descubrimiento para que Home Assistant no conserve entidades huérfanas.
5. **Given** un reinicio de Home Assistant, **When** vuelve a suscribirse, **Then** recupera las
   entidades y su último estado sin que haya que reiniciar el servicio.

---

### User Story 2 - Que Home Assistant tampoco mienta (Priority: P1)

Un panel de Home Assistant que muestra un acumulador «encendido» cuando nadie puede confirmarlo
es exactamente el mismo problema que se resolvió en la API y en el panel web, un metro más allá.
Home Assistant tiene un tercer estado, `unavailable`, y es el que corresponde cuando no hay
prueba. Además, si el publicador muere o el túnel se cae, las entidades deben quedar
inmediatamente como no disponibles en lugar de conservar el último valor para siempre.

**Why this priority**: es la continuidad del trabajo de las tres fases anteriores. Aquí la
información sale del proyecto y entra en las automatizaciones de alguien, donde un dato falso deja
de ser un panel confuso y se convierte en una acción equivocada.

**Independent Test**: se provoca cada situación —controlador no visible, publicador detenido,
túnel caído— y se comprueba qué ve Home Assistant en cada caso.

**Acceptance Scenarios**:

1. **Given** un controlador vivo, **When** se mira Home Assistant, **Then** el estado de cada
   salida se publica como valor real.
2. **Given** un controlador que no se ve desde hace más tiempo del tolerado, **When** se mira Home
   Assistant, **Then** las entidades de estado de salida quedan **no disponibles**, y no como
   apagadas.
3. **Given** un estado no vigente, **When** se mira la potencia instantánea, **Then** esa entidad
   queda **no disponible**, y no publica un cero.
4. **Given** el servicio publicador que se detiene o muere, **When** Home Assistant lo detecta,
   **Then** todas las entidades quedan no disponibles sin intervención, y no conservan el último
   valor indefinidamente.
5. **Given** una caída del túnel o del broker, **When** se restablece, **Then** el servicio se
   reconecta solo, republica el descubrimiento y vuelve a publicar el estado.
6. **Given** la sospecha de más de un controlador, **When** se mira Home Assistant, **Then** hay
   una entidad que lo señala, apta para disparar una notificación.
7. **Given** un controlador vivo pero degradado, **When** se mira Home Assistant, **Then** se
   distingue de uno sano y de uno ausente.

---

### User Story 3 - Automatizar la carga desde Home Assistant (Priority: P1)

Quien usa Home Assistant habilita o deshabilita un acumulador y ajusta su carga objetivo desde una
automatización o desde el panel de HA. Ninguna de esas dos acciones acciona un relé: cambian la
configuración, y el planificador decide. La potencia máxima y la asignación de pines quedan fuera
del alcance de Home Assistant.

**Why this priority**: es lo que convierte la integración en algo útil y no solo informativo, y es
lo que el usuario pidió explícitamente.

**Independent Test**: se publican órdenes válidas e inválidas en los asuntos de mando y se
comprueba qué queda almacenado y qué se rechaza.

**Acceptance Scenarios**:

1. **Given** un acumulador habilitado, **When** Home Assistant lo deshabilita, **Then** la
   configuración cambia, el cambio se refleja en la entidad, y el plan lo recoge en el siguiente
   recálculo.
2. **Given** un acumulador, **When** Home Assistant cambia su carga objetivo a un valor válido,
   **Then** la configuración cambia y la entidad refleja el valor nuevo.
3. **Given** un valor fuera de rango, **When** se publica, **Then** se rechaza, se registra el
   motivo, y la entidad vuelve a reflejar el valor realmente almacenado, no el ordenado.
4. **Given** una orden sobre un campo que Home Assistant **no** puede cambiar —potencia máxima,
   pin, nivel activo—, **When** se publica en cualquier asunto, **Then** no se aplica y se
   registra el intento.
5. **Given** una orden y otra escritura concurrente desde el panel web, **When** ambas ocurren,
   **Then** ninguna se pierde en silencio: una se aplica y la otra se rechaza y se reintenta con
   la revisión vigente.
6. **Given** cualquier orden, **When** se procesa, **Then** ninguna acciona una salida
   directamente: todas pasan por la configuración y el planificador.

---

### User Story 4 - Cerrar el lazo con la temperatura real de la estancia (Priority: P2)

Hoy el modelo térmico asume que cada estancia está a su temperatura objetivo y calcula la carga
solo a partir de la temperatura exterior prevista. Quien usa Home Assistant ya tiene sensores de
temperatura interior, así que puede declarar cuál corresponde a cada acumulador y el modelo usará
la medida real. Si esa medida falta, llega vieja o es absurda, el modelo vuelve al comportamiento
anterior, lo registra, y sigue planificando.

**Why this priority**: es la mejora funcional con más valor real de las cuatro fases, porque
cierra el lazo: una estancia que ya está caliente deja de cargarse como si estuviera fría. Va en
P2 porque el sistema funciona sin ella y porque introduce una dependencia externa en el
planificador, que es el componente más delicado.

**Independent Test**: se alimenta al modelo con temperaturas interiores válidas, ausentes, viejas
y absurdas, y se comprueba la demanda calculada y lo registrado en cada caso.

**Acceptance Scenarios**:

1. **Given** un acumulador con temperatura interior declarada y una medida reciente por debajo de
   su objetivo, **When** se calcula la demanda, **Then** se usa la medida real y la carga
   resultante refleja el déficit real de la estancia.
2. **Given** una estancia que ya está a su temperatura objetivo o por encima, **When** se calcula
   la demanda, **Then** la carga solicitada es la mínima configurada para ese acumulador, no la
   que correspondería a la temperatura exterior.
3. **Given** un acumulador sin temperatura interior declarada, **When** se calcula la demanda,
   **Then** el comportamiento es **idéntico** al de antes de esta fase.
4. **Given** una temperatura declarada pero sin ninguna medida recibida, **When** se calcula la
   demanda, **Then** se usa la reserva —el comportamiento anterior—, y se registra una sola vez al
   entrar en ese estado.
5. **Given** una medida más antigua que la tolerancia configurada, **When** se calcula la demanda,
   **Then** se trata como ausente y se usa la reserva.
6. **Given** una medida fuera de un rango físicamente plausible, **When** se recibe, **Then** se
   descarta con un registro de error y se usa la reserva.
7. **Given** una medida que vuelve a llegar tras una ausencia, **When** se calcula la demanda,
   **Then** se usa de nuevo y se registra la recuperación una sola vez.
8. **Given** cualquier fallo relacionado con la temperatura interior, **When** ocurre, **Then**
   el plan se sigue generando y ninguna salida queda en estado indeterminado.

---

### User Story 5 - Conectar con un Home Assistant que no está en la misma red (Priority: P1)

Quien despliega puede tener Home Assistant en otra ubicación, alcanzable a través de un túnel. El
servicio se conecta a la dirección que se le indique, con las credenciales que se le den, y
sobrevive a que ese túnel se caiga y vuelva.

**Why this priority**: es la condición que el usuario puso, y determina el comportamiento ante
fallo de toda la fase.

**Independent Test**: se apunta el servicio a un broker inalcanzable, se comprueba su
comportamiento, se hace alcanzable y se comprueba la recuperación.

**Acceptance Scenarios**:

1. **Given** una dirección de broker, un puerto y unas credenciales configurados, **When** arranca
   el servicio, **Then** se conecta y publica.
2. **Given** un broker inalcanzable al arrancar, **When** el servicio arranca, **Then** reintenta
   con espera creciente, lo registra, y **no** termina el proceso.
3. **Given** una conexión establecida que se pierde, **When** ocurre, **Then** el servicio
   reintenta con espera creciente y republica el descubrimiento al reconectar.
4. **Given** una reconexión, **When** se completa, **Then** Home Assistant recupera las entidades
   sin intervención manual.
5. **Given** un broker que exige credenciales, **When** las configuradas son incorrectas,
   **Then** se registra de forma accionable y no se reintenta en un bucle apretado.
6. **Given** cualquier fallo de conexión prolongado, **When** ocurre, **Then** ni el controlador
   ni la API ni el panel web se ven afectados.
7. **Given** un broker que se alcanza por una red no confiable, **When** se configura,
   **Then** existe la opción de cifrar la conexión, y la documentación explica cuándo hace falta y
   cuándo el túnel ya lo cubre.

---

### User Story 6 - Desplegarlo sin tocar lo que ya funciona (Priority: P1)

Quien despliega instala el publicador como un servicio propio, independiente del controlador, de
la API y del panel. Puede pararlo sin que nada más se entere.

**Why this priority**: es la propiedad que ya protege al controlador en las fases anteriores, y
esta fase añade una dependencia de red nueva, que es justo lo que no debe poder tocar el control.

**Independent Test**: se detiene y se arranca cada servicio por separado y se observa el efecto en
los demás.

**Acceptance Scenarios**:

1. **Given** los cuatro servicios en marcha, **When** se detiene el publicador, **Then** el
   controlador sigue ejecutando su plan y la API sigue respondiendo.
2. **Given** el publicador en marcha, **When** se detiene el controlador, **Then** el publicador
   sigue publicando y refleja que el controlador no está visible.
3. **Given** la instalación del publicador, **When** se ejecuta, **Then** no arranca ni habilita
   ningún servicio automáticamente y no requiere compilador.
4. **Given** cualquier operación del publicador, **When** se ejecuta, **Then** no acciona ninguna
   salida ni construye el medio para accionarla.
5. **Given** la documentación, **When** se lee, **Then** describe el despliegue, la conexión a
   través de un túnel, y cómo declarar las temperaturas interiores.

---

### Edge Cases

- El broker acepta la conexión pero rechaza la publicación por permisos: se registra de forma
  accionable y no se interpreta como éxito.
- Llega una orden retenida desde el broker: se rechaza y se registra sin modificar configuración;
  después se republica el estado realmente almacenado.
- Home Assistant no está en marcha aunque el broker sí: el servicio publica igualmente y Home
  Assistant recoge el estado al arrancar.
- Llegan órdenes para un acumulador que ya no existe en la configuración: se rechazan con registro
  y no crean nada.
- Llegan dos órdenes contradictorias en rápida sucesión: se aplican en orden y el resultado final
  es determinista.
- El reloj del equipo de Home Assistant no coincide con el del dispositivo: la antigüedad de la
  temperatura interior se evalúa con el instante de recepción del dispositivo, no con el que venga
  en el mensaje.
- La temperatura interior llega con un valor no numérico o vacío: se descarta con registro.
- La base de datos no está accesible: el publicador marca las entidades como no disponibles en
  lugar de publicar datos inventados, y reintenta.
- El esquema de la base de datos necesita migración: el publicador no publica estado y lo
  registra, sin intentar migrar nada.
- El túnel se cae justo entre la publicación del descubrimiento y la del estado: al reconectar se
  republica el descubrimiento antes del estado.
- Una automatización de Home Assistant deshabilita todos los acumuladores: la configuración lo
  acepta, el plan resultante está vacío y todas las salidas quedan apagadas.

## Requirements *(mandatory)*

### Functional Requirements

**Descubrimiento y publicación**

- **FR-001**: El servicio MUST publicar la definición de las entidades de forma que Home Assistant
  las cree automáticamente, sin configuración manual en Home Assistant.
- **FR-002**: El servicio MUST publicar un dispositivo por instalación y uno por acumulador, de
  modo que las entidades queden agrupadas de forma reconocible.
- **FR-003**: El servicio MUST publicar, por acumulador: el estado de su salida, su potencia
  nominal, si está habilitado, su carga objetivo, y los minutos solicitados, asignados y no
  atendidos del plan vigente.
- **FR-004**: El servicio MUST publicar, por instalación: la potencia instantánea total y su
  porcentaje del límite, el límite configurado, la ventana del plan en curso, la previsión
  utilizada con su origen, la salud del controlador, y la sospecha de más de un controlador.
- **FR-005**: Un acumulador añadido a la configuración MUST aparecer en Home Assistant sin
  reiniciarlo, y uno eliminado MUST retirarse para no dejar entidades huérfanas.
- **FR-006**: El estado MUST publicarse de forma que Home Assistant lo recupere tras reiniciarse,
  sin reiniciar el servicio.
- **FR-007**: Los nombres e identificadores de las entidades MUST ser estables entre reinicios,
  para no romper automatizaciones ya escritas. Los identificadores MUST usar el segmento fijo
  `installation` y el id de dominio del acumulador, y MUST NOT depender del nombre editable de la
  instalación, del prefijo de asuntos, de una clave interna ni del orden.

**Honestidad de lo publicado**

- **FR-008**: Cuando la proyección de estado compartida indique que el estado de las salidas no es
  vigente, las entidades correspondientes MUST publicarse como **no disponibles**, y MUST NOT
  publicarse como apagadas.
- **FR-009**: Con el estado no vigente, la potencia instantánea MUST quedar no disponible y
  MUST NOT publicarse como cero.
- **FR-010**: El servicio MUST declarar al broker una última voluntad, de modo que si el proceso
  muere o pierde la conexión, Home Assistant marque las entidades como no disponibles sin
  intervención.
- **FR-011**: El servicio MUST distinguir las cuatro situaciones del controlador —sano, degradado,
  silencioso y nunca visto— en lo que publica.
- **FR-012**: La sospecha de más de un controlador MUST publicarse como una entidad apta para
  disparar una notificación.
- **FR-013**: Una base de datos inaccesible o un esquema que el servicio no comprenda MUST
  resultar en entidades no disponibles y en un registro accionable, y MUST NOT en datos
  inventados.

**Órdenes desde Home Assistant**

- **FR-014**: El servicio MUST aceptar órdenes para habilitar o deshabilitar un acumulador y para
  cambiar su carga objetivo.
- **FR-015**: El servicio MUST NOT aceptar órdenes sobre ningún otro campo de configuración. En
  particular, potencia máxima, asignación de pin y nivel activo MUST quedar fuera del alcance de
  Home Assistant.
- **FR-016**: Ninguna orden MUST accionar una salida directamente: toda orden MUST aplicarse como
  cambio de configuración y MUST tomar efecto a través del planificador.
- **FR-017**: Toda orden MUST validarse con las mismas reglas que cualquier otra escritura de
  configuración, sin relajar ninguna.
- **FR-018**: Una orden rechazada MUST registrarse con su motivo, y la entidad MUST volver a
  reflejar el valor **realmente almacenado**, no el ordenado.
- **FR-019**: Una orden concurrente con otra escritura MUST NOT perder ningún cambio en silencio:
  MUST resolverse mediante la revisión y reintentarse con la vigente.
- **FR-020**: Un intento de orden sobre un campo no admitido o sobre un acumulador inexistente
  MUST registrarse y MUST NOT crear ni modificar nada.
- **FR-048**: Toda orden recibida con el indicador MQTT de mensaje retenido MUST rechazarse y
  registrarse sin cambiar configuración; el servicio MUST republicar con retención el estado
  realmente almacenado.

**Temperatura interior y lazo cerrado**

- **FR-021**: Cada acumulador MUST poder declarar, de forma opcional, un origen de temperatura
  interior de su estancia. Establecer ese campo a una cadena vacía mediante CLI, API o panel MUST
  eliminar el origen y devolver el acumulador al comportamiento anterior.
- **FR-022**: Cuando exista una medida de temperatura interior reciente y plausible, el modelo
  térmico MUST usarla en lugar de asumir que la estancia está a su temperatura objetivo.
- **FR-023**: Un acumulador sin temperatura interior declarada MUST comportarse **exactamente**
  como antes de esta fase.
- **FR-024**: La ausencia de medida, una medida más antigua que una tolerancia configurable, o un
  valor fuera de un rango físicamente plausible MUST tratarse como ausencia y MUST provocar el uso
  de la reserva, que es el comportamiento anterior.
- **FR-025**: La entrada y la salida del uso de la reserva MUST registrarse una sola vez en cada
  transición, y MUST NOT en cada cálculo.
- **FR-026**: La antigüedad de una medida MUST evaluarse con el instante en que el dispositivo la
  recibió, y MUST NOT con un instante que venga dentro del mensaje.
- **FR-027**: Ningún fallo relacionado con la temperatura interior MUST impedir la generación del
  plan ni dejar una salida en estado indeterminado.
- **FR-028**: El planificador y el modelo térmico MUST seguir siendo funciones deterministas sin
  I/O: la temperatura interior MUST llegarles como dato, nunca leída por ellos.
- **FR-029**: Una estancia que ya alcanzó o superó su temperatura objetivo MUST resultar en la
  carga mínima configurada para ese acumulador.
- **FR-045**: El publicador MUST guardar en la base de datos la medida vigente más reciente de cada
  acumulador y el instante en que este dispositivo la recibió; el controlador MUST leer esas
  medidas al recalcular el plan y pasarlas como datos al modelo térmico.
- **FR-046**: Una medida persistida MUST reemplazarse atómicamente por la siguiente del mismo
  acumulador y MUST eliminarse al eliminar ese acumulador; el publicador y el controlador MUST
  seguir siendo procesos independientes y el controlador MUST NOT conectarse al broker.
- **FR-047**: Una entrada vacía, no numérica o fuera del rango plausible MUST invalidar
  atómicamente cualquier medida anterior almacenada para ese acumulador, de modo que el siguiente
  recálculo use la reserva en lugar de seguir usando un valor anterior aparentemente válido.

**Conexión y resistencia**

- **FR-030**: La dirección, el puerto y las credenciales del broker MUST ser configurables, y las
  credenciales MUST proceder del mecanismo protegido del despliegue, nunca de la base de datos ni
  del repositorio ni de los logs.
- **FR-031**: Un broker inalcanzable al arrancar MUST provocar reintentos con espera creciente y
  MUST NOT terminar el proceso.
- **FR-032**: Una conexión perdida MUST provocar reconexión con espera creciente, y al reconectar
  MUST republicarse el descubrimiento **antes** del estado.
- **FR-033**: Un rechazo de credenciales MUST registrarse de forma accionable y MUST NOT
  reintentarse en un bucle apretado: MUST registrarse una vez al entrar en ese estado y
  reintentarse cada **5 minutos** hasta que las credenciales sean aceptadas; la recuperación MUST
  registrarse una vez.
- **FR-034**: El servicio MUST ofrecer la opción de cifrar la conexión al broker, y la
  documentación MUST explicar cuándo hace falta y cuándo un túnel ya lo cubre.
- **FR-035**: Ningún fallo de conexión, por prolongado que sea, MUST afectar al controlador, a la
  API ni al panel web.
- **FR-049**: Las publicaciones de descubrimiento, disponibilidad y estado MUST usar MQTT v5 con
  QoS 1 y MUST comprobar la confirmación del broker. Un PUBACK de rechazo por permisos MUST
  registrarse de forma accionable y MUST NOT interpretarse como publicación correcta.

**Despliegue y aislamiento**

- **FR-036**: El publicador MUST ejecutarse como un servicio independiente del controlador, de la
  API y del panel.
- **FR-037**: Ninguna operación del publicador MUST accionar una salida física ni construir el
  medio para accionarla.
- **FR-038**: Detener el publicador MUST NOT afectar en modo alguno al control de las salidas.
- **FR-039**: La dependencia del cliente de mensajería MUST vivir en un extra opcional, y el
  planificador MUST poder importarse y ejecutarse sin ella instalada.
- **FR-040**: La instalación MUST NOT requerir compilador ni herramientas de construcción nativas,
  y MUST NOT arrancar ni habilitar el servicio automáticamente.
- **FR-041**: La documentación MUST describir el despliegue, la conexión a un Home Assistant
  remoto a través de un túnel, cómo declarar las temperaturas interiores, y qué entidades se
  publican.

**Pruebas**

- **FR-042**: La suite MUST poder ejecutarse completa sin red, sin broker real, sin Home
  Assistant, sin base de datos remota y sin hardware.
- **FR-043**: MUST tener cobertura explícita: entidades no disponibles en cada situación no
  vigente, última voluntad declarada, reconexión con espera creciente, rechazo de órdenes no
  admitidas, y los cuatro caminos de reserva de la temperatura interior.
- **FR-044**: Las suites existentes de Python y del panel MUST seguir pasando sin cambios de
  comportamiento.

### Key Entities

- **Dispositivo publicado**: la agrupación con la que Home Assistant presenta las entidades. Uno
  por instalación y uno por acumulador.
- **Entidad publicada**: un dato observable en Home Assistant, con su identificador estable, su
  tipo y su disponibilidad. La disponibilidad es tan importante como el valor.
- **Definición de descubrimiento**: el mensaje que hace que Home Assistant cree una entidad sin
  configuración manual. Se republica al reconectar.
- **Última voluntad**: lo que el broker publica en nombre del servicio cuando este desaparece. Es
  lo que convierte una muerte silenciosa en entidades no disponibles.
- **Orden**: una petición de Home Assistant para cambiar uno de los dos campos admitidos. Se
  aplica como cambio de configuración validado, nunca como accionamiento.
- **Medida de temperatura interior**: el último valor válido de un acumulador, guardado en la base
  de datos junto con el instante en que el dispositivo lo recibió. El publicador lo reemplaza al
  recibir una medida nueva y el controlador lo lee al recalcular el plan. Tiene tolerancia de
  antigüedad y rango de plausibilidad; fuera de cualquiera de los dos, se trata como ausente.
- **Estado de reserva térmica**: si el modelo está usando medidas reales o ha vuelto al
  comportamiento anterior. Su transición es lo que se registra, no cada cálculo.

Las entidades de configuración, histórico y estado son las de las fases anteriores y no se
redefinen aquí.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Las entidades aparecen en Home Assistant sin escribir una línea de configuración
  allí, y agrupadas por instalación y acumulador.
- **SC-002**: Home Assistant **nunca** muestra una salida como apagada cuando en realidad no se
  puede confirmar: en toda situación no vigente esas entidades quedan no disponibles.
- **SC-003**: Matar el proceso publicador deja las entidades no disponibles en Home Assistant sin
  intervención de nadie.
- **SC-004**: Un operador automatiza el encendido de una estancia cambiando su carga objetivo desde
  Home Assistant, y el cambio se refleja en el siguiente plan.
- **SC-005**: Ninguna orden de Home Assistant puede cambiar la potencia máxima, un pin o un nivel
  activo.
- **SC-006**: Ninguna orden de Home Assistant puede accionar una salida: verificable porque el
  publicador no tiene acceso al medio de accionarlas.
- **SC-007**: Una estancia que ya está a su temperatura objetivo deja de cargarse como si estuviera
  fría, y el ahorro es observable comparando la demanda calculada con y sin medida.
- **SC-008**: La pérdida de las medidas de temperatura interior devuelve el comportamiento exacto
  anterior a esta fase, sin dejar de generar plan.
- **SC-009**: Un túnel que se cae y vuelve no requiere intervención: el servicio se reconecta y
  Home Assistant recupera las entidades.
- **SC-010**: Detener el publicador durante al menos **2 horas** no produce ningún cambio
  observable en el estado de las salidas ni en la ejecución del plan.
- **SC-011**: La instalación en el dispositivo no requiere compilador; el publicador arranca en
  menos de **5 s**, consume menos de **70 MB RSS**, y el conjunto de los cuatro servicios consume
  menos de **250 MB RSS** en la Raspberry Pi 2B.
- **SC-012**: La suite completa se ejecuta sin red, sin broker, sin Home Assistant y sin hardware.
- **SC-013**: Las suites existentes siguen pasando íntegras.

## Assumptions

- Home Assistant ya dispone de un broker de mensajería, o quien despliega instala uno. Instalarlo
  y configurarlo queda fuera de alcance.
- El túnel que da acceso a un Home Assistant remoto se configura fuera de este proyecto. Lo que
  sí es del proyecto es sobrevivir a que se caiga.
- Cuando el broker se alcanza por un túnel cifrado, el cifrado de la conexión al broker es
  opcional. Cuando se alcanza por una red no confiable, no lo es. La documentación lo explica; la
  decisión es del operador.
- Las medidas de temperatura interior llegan al dispositivo por el mismo canal de mensajería, sin
  necesidad de credenciales de Home Assistant. Quien despliega configura en Home Assistant la
  publicación de esos valores.
- La base de datos compartida es el canal entre el publicador que recibe las temperaturas y el
  controlador que recalcula el plan; no se añade MQTT ni otro canal de red al controlador.
- Una sola instalación y un solo Home Assistant. No se contempla publicar varias instalaciones al
  mismo broker con distinción entre ellas más allá de un prefijo configurable.
- La instalación publicada usa el identificador lógico fijo `installation`; su nombre visible
  puede cambiar sin alterar ids de dispositivo, `unique_id` ni automatizaciones.
- Sin forzado manual de salidas desde Home Assistant, coherente con las fases anteriores: la API
  no lo ofrece y esta fase no lo añade.
- El modelo térmico sigue siendo lineal. Usar la temperatura interior real cambia su entrada, no
  su forma.
- La tolerancia de antigüedad de una medida y el rango plausible son configurables, con valores por
  defecto conservadores.
- Sin control de acceso por entidad: quien puede publicar en el broker puede dar las dos órdenes
  admitidas. Acotarlo más requeriría permisos en el broker, que se documentan pero no se gestionan.
