# Feature Specification: API HTTP de estado y configuración

**Feature Branch**: `002-config-api`

**Created**: 2026-08-26

**Status**: Draft

**Input**: User description: "API HTTP de lectura y configuración sobre la instalación, servida como proceso independiente del controlador. Dos unidades de servicio separadas que se comunican por base de datos, autenticación por token en variable de entorno, sin control manual de salidas, estado en vivo por consulta periódica."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ver de un vistazo qué está pasando ahora (Priority: P1)

Quien opera la instalación consulta un único punto de la API y obtiene la fotografía completa
del momento: qué acumuladores están cargando, cuánta potencia se está consumiendo y qué
fracción del límite representa, cuál es el plan en curso con su ventana, qué previsión se usó
para calcularlo y de dónde vino, y cuántos minutos de los solicitados quedaron sin atender.

**Why this priority**: Es la razón de ser de la API y lo primero que necesita el frontend de
la fase siguiente. Sin ella no hay nada que mostrar.

**Independent Test**: Con una instalación y un histórico conocidos, se consulta el estado y se
comprueba que cada dato coincide con lo que el planificador y el controlador registraron.

**Acceptance Scenarios**:

1. **Given** un controlador en marcha con un plan activo, **When** se consulta el estado,
   **Then** se obtienen los acumuladores actualmente activos, la potencia instantánea total,
   el porcentaje del límite configurado, la ventana del plan en curso y el instante de la
   consulta.
2. **Given** un plan generado a partir de la previsión de reserva porque el proveedor real
   falló, **When** se consulta el estado, **Then** la previsión mostrada indica que su origen
   fue el valor de reserva.
3. **Given** un plan que no cubre toda la carga solicitada, **When** se consulta el estado,
   **Then** se obtienen los minutos solicitados, asignados y no atendidos de cada acumulador.
4. **Given** una instalación sin ningún plan todavía, **When** se consulta el estado,
   **Then** la respuesta lo indica explícitamente y ningún acumulador aparece como activo.

---

### User Story 2 - No creerse un estado obsoleto (Priority: P1)

La API y el controlador son procesos distintos que solo se comunican por la base de datos. Si
el controlador está parado, colgado o ha muerto, la última transición registrada sigue ahí y
la API la mostraría como si fuera el estado actual: acumuladores encendidos que en realidad
están apagados. Para evitarlo, el controlador publica periódicamente una señal de vida, y la
API distingue siempre «esto está pasando ahora» de «esto es lo último que se supo, y el
controlador no aparece desde tal instante».

**Why this priority**: Es la consecuencia directa de separar los procesos y la única forma de
que la información sea honesta. Un panel que afirma que un acumulador de 2,8 kW está cargando
cuando no lo está es peor que un panel que dice «no lo sé»: induce decisiones equivocadas
sobre la instalación eléctrica.

**Independent Test**: Con un reloj controlado, se deja de publicar la señal de vida y se
comprueba que el estado pasa a marcarse como no vigente sin cambiar los datos históricos.

**Acceptance Scenarios**:

1. **Given** un controlador que publica su señal de vida con normalidad, **When** se consulta
   el estado, **Then** se indica que el controlador está vivo, con el instante de su última
   señal, y el estado de las salidas se presenta como vigente.
2. **Given** un controlador que dejó de publicar su señal hace más tiempo del tolerado,
   **When** se consulta el estado, **Then** el estado de las salidas se marca explícitamente
   como **no vigente**, se indica desde cuándo no se ve al controlador, y **no** se afirma que
   ningún acumulador esté activo.
3. **Given** un controlador que nunca ha publicado una señal de vida, **When** se consulta el
   estado, **Then** se informa de que el controlador no ha arrancado nunca, sin inventar
   ningún estado de salida.
4. **Given** un controlador que se recupera y vuelve a publicar su señal, **When** se consulta
   el estado, **Then** vuelve a presentarse como vigente sin intervención manual.
5. **Given** un controlador que está vivo pero en estado degradado porque no alcanza la base
   de datos, **When** se consulta el estado, **Then** se distingue esa situación tanto de un
   controlador sano como de un controlador ausente.

---

### User Story 3 - Editar la configuración desde un cliente (Priority: P1)

Quien opera la instalación cambia parámetros de la instalación y de cada acumulador, y añade o
elimina acumuladores, con exactamente las mismas garantías que ya ofrece la línea de comandos:
la configuración completa resultante se valida antes de aplicarse, el cambio es atómico, un
valor con aspecto de credencial se rechaza, y dos clientes que editan a la vez no pueden
perder silenciosamente el cambio del otro.

**Why this priority**: Sin edición, el frontend de la fase siguiente es un visor y la
configuración real seguiría requiriendo acceso por consola a la Raspberry Pi.

**Independent Test**: Se aplican cambios válidos e inválidos por la API y se comprueba, leyendo
después, qué quedó almacenado y qué se rechazó.

**Acceptance Scenarios**:

1. **Given** una configuración almacenada válida, **When** se modifica un parámetro a un valor
   válido, **Then** el cambio queda almacenado, la respuesta indica el valor anterior, el nuevo
   y la revisión resultante, y una lectura posterior refleja el valor nuevo.
2. **Given** una configuración almacenada válida, **When** se intenta un cambio que dejaría la
   configuración global inválida, **Then** no se aplica nada, el almacén queda exactamente
   como estaba, y el error identifica el campo y el conflicto.
3. **Given** dos clientes que leyeron la misma revisión, **When** ambos intentan escribir,
   **Then** el primero tiene éxito y el segundo recibe un error de conflicto que le indica
   releer, y ningún cambio se pierde en silencio.
4. **Given** un intento de guardar una credencial o una cadena de conexión en un campo de
   configuración, **When** se envía, **Then** se rechaza indicando que los secretos se sirven
   por variable de entorno.
5. **Given** una configuración almacenada, **When** se añade un acumulador con todos sus datos
   obligatorios, **Then** queda almacenado; **When** se elimina uno, **Then** desaparece junto
   con su salida y su perfil térmico, y su histórico se conserva.
6. **Given** un controlador ejecutando un plan, **When** se edita la configuración, **Then**
   el plan en curso no se altera y el cambio toma efecto en el siguiente recálculo.
7. **Given** un campo o un acumulador inexistente, **When** se intenta editar, **Then** el
   error enumera los nombres admitidos o los acumuladores existentes, y no se modifica nada.

---

### User Story 4 - Impedir que un desconocido cambie la instalación (Priority: P1)

La API expone la edición de la configuración de un sistema que conmuta cargas eléctricas
reales. Toda operación exige un secreto compartido que quien opera la instalación conoce y que
vive fuera de la base de datos. Sin ese secreto, o con uno incorrecto, no se ejecuta nada, ni
lectura ni escritura, y el intento queda registrado sin revelar el secreto ofrecido.

**Why this priority**: Cambiar la potencia máxima o la asignación de pines desde la red
doméstica sin credencial es un riesgo eléctrico, no solo de privacidad. Va en la misma fase
que introduce la superficie de red.

**Independent Test**: Se repite cada operación de la API sin credencial, con una incorrecta y
con la correcta, comprobando qué se ejecuta en cada caso.

**Acceptance Scenarios**:

1. **Given** la API en marcha, **When** se hace cualquier petición sin credencial, **Then** se
   rechaza sin ejecutar la operación y sin revelar si la instalación existe.
2. **Given** la API en marcha, **When** se hace una petición con una credencial incorrecta,
   **Then** se rechaza igual que si no hubiera ninguna, sin indicar en qué se diferencia de la
   correcta.
3. **Given** una credencial correcta, **When** se hace cualquier operación admitida, **Then**
   se ejecuta.
4. **Given** cualquier intento rechazado, **When** se revisan los registros, **Then** consta el
   intento y **no** consta el valor de la credencial ofrecida.
5. **Given** un despliegue sin credencial configurada, **When** se arranca la API, **Then** el
   arranque falla con un mensaje accionable y **no** se queda escuchando sin protección.

---

### User Story 5 - Que la API no pueda romper la calefacción (Priority: P1)

La API se despliega y se opera de forma independiente del controlador. Puede arrancarse,
detenerse, reiniciarse o fallar sin que el control de los relés se vea afectado en absoluto, y
sin que ninguna operación suya active una salida. Recíprocamente, la API no depende de que el
controlador esté vivo para responder: informa de su ausencia en lugar de bloquearse.

**Why this priority**: Es la razón por la que se eligieron dos procesos separados, y es lo que
el Principio I exige verificar de forma explícita en cualquier interfaz nueva.

**Independent Test**: Se detiene y se arranca cada proceso por separado y se observa el efecto
en el otro y en el estado de las salidas.

**Acceptance Scenarios**:

1. **Given** un controlador ejecutando un plan, **When** la API se detiene o falla, **Then** el
   controlador sigue ejecutando su plan sin alteración.
2. **Given** una API en marcha, **When** el controlador se detiene, **Then** la API sigue
   respondiendo y marca el estado como no vigente.
3. **Given** cualquier operación de la API, **When** se ejecuta, **Then** no se acciona ninguna
   salida física ni se construye ningún medio para accionarla.
4. **Given** la base de datos inaccesible, **When** se hace cualquier petición, **Then** se
   responde con un error claro y sin traza técnica, nunca con un estado inventado, y la API no
   se queda colgada.
5. **Given** una configuración almacenada inválida o un esquema que la API no comprende,
   **When** se consulta, **Then** se informa del problema y de cómo corregirlo, y no se ofrece
   ninguna operación de escritura sobre datos que no se comprenden.

---

### User Story 6 - Auditar el pasado desde un cliente (Priority: P2)

Quien opera la instalación consulta el histórico por rango de fechas y de forma paginada:
planes generados, previsiones utilizadas y transiciones de salida. Con eso puede reconstruir
cualquier noche sin acceder a la Raspberry Pi.

**Why this priority**: Es lo que da contenido a las gráficas del frontend, pero el estado
actual y la edición son más urgentes.

**Independent Test**: Con un histórico sembrado de varias noches, se consulta con distintos
rangos y páginas y se comprueba qué se devuelve.

**Acceptance Scenarios**:

1. **Given** un histórico de varias noches, **When** se consultan los planes de un rango de
   fechas, **Then** se devuelven solo los de ese rango, ordenados de más reciente a más
   antiguo, con indicación de si hay más resultados.
2. **Given** un histórico grande, **When** se consulta sin límite explícito, **Then** se
   devuelve una página de tamaño acotado por defecto, nunca el histórico completo.
3. **Given** un rango sin datos, **When** se consulta, **Then** se devuelve una página vacía,
   no un error.
4. **Given** un rango con el inicio posterior al fin, **When** se consulta, **Then** se rechaza
   indicando el problema.
5. **Given** un acumulador ya eliminado de la configuración, **When** se consulta el histórico
   de una noche en que existía, **Then** sus transiciones y minutos siguen apareciendo.

---

### User Story 7 - Descubrir la API sin leer el código (Priority: P2)

Quien vaya a construir un cliente —el frontend de la fase siguiente, la integración domótica
de la fase cuatro, o un script propio— obtiene de la propia API la descripción de todas sus
operaciones, sus parámetros, sus respuestas y sus errores.

**Why this priority**: Ahorra trabajo en las dos fases siguientes y evita que el contrato viva
solo en la cabeza de quien lo escribió. No es urgente para operar la instalación.

**Independent Test**: Se solicita la descripción de la API y se comprueba que enumera todas las
operaciones realmente disponibles.

**Acceptance Scenarios**:

1. **Given** la API en marcha, **When** se solicita su descripción, **Then** se enumeran todas
   las operaciones disponibles con sus parámetros, respuestas y códigos de error.
2. **Given** la descripción de la API, **When** se compara con las operaciones realmente
   servidas, **Then** coinciden: no hay operaciones documentadas que no existan ni operaciones
   servidas sin documentar.
3. **Given** la descripción de la API, **When** se revisa, **Then** no contiene ningún secreto
   ni ningún valor real de la configuración.

---

### User Story 8 - Mantener el histórico acotado desde un cliente (Priority: P3)

Quien opera la instalación dispara la limpieza de retención desde la API y obtiene el recuento
de lo eliminado, sin necesidad de acceder por consola.

**Why this priority**: La limpieza ya se ejecuta de forma automática tras cada refresco de
plan; poder dispararla a mano es una comodidad, no una necesidad.

**Independent Test**: Con un histórico que excede la retención, se dispara la limpieza por la
API y se comprueba el recuento y qué sobrevive.

**Acceptance Scenarios**:

1. **Given** un histórico con registros más antiguos que la retención, **When** se dispara la
   limpieza, **Then** se devuelve el recuento por tabla y la configuración y los planes vivos
   se conservan.
2. **Given** una retención ilimitada, **When** se dispara la limpieza, **Then** no se elimina
   nada y la respuesta lo indica.

---

### Edge Cases

- La credencial configurada es una cadena vacía o un valor de ejemplo evidente: el arranque se
  rechaza en lugar de quedar escuchando con una credencial trivial.
- Dos clientes consultan el estado a la vez mientras el controlador escribe una transición:
  ninguno observa un estado a medias.
- El controlador escribe su señal de vida y muere inmediatamente después: el estado se marca
  como no vigente en cuanto se supera la tolerancia, sin necesidad de reiniciar la API.
- El reloj del sistema salta hacia atrás: la señal de vida no se interpreta como venida del
  futuro ni como caducada para siempre.
- La base de datos se vuelve inaccesible entre dos peticiones: la primera responde con datos y
  la segunda con un error claro, sin que la API muera.
- El histórico está vacío porque la retención acaba de limpiarlo: las consultas devuelven
  páginas vacías, no errores.
- Se pide una página de histórico desmesuradamente grande: el tamaño se acota al máximo
  admitido y la respuesta lo indica.
- Se elimina el último acumulador: el estado sigue siendo consultable y no muestra ninguna
  salida activa.
- Un cliente consulta el estado con una frecuencia muy superior a la prevista: la API sigue
  respondiendo sin degradar el controlador, que es un proceso distinto.
- La API arranca antes de que la base de datos esté inicializada: informa de que falta
  inicializarla en lugar de fallar de forma opaca.

## Requirements *(mandatory)*

> **Nota de orden**: los bloques agrupan por tema, y la numeración es corrida dentro de cada
> bloque en el orden en que aparecen.

### Functional Requirements

**Despliegue e independencia de procesos**

- **FR-001**: La API MUST ejecutarse como un servicio independiente del controlador
  persistente, y ambos MUST comunicarse exclusivamente a través de la base de datos.
- **FR-002**: Detener, reiniciar o hacer fallar la API MUST NOT afectar en modo alguno al
  control de las salidas.
- **FR-003**: La API MUST responder aunque el controlador esté detenido, informando de su
  ausencia; MUST NOT bloquearse ni fallar por esa causa.
- **FR-004**: Ninguna operación de la API MUST accionar una salida física ni construir el medio
  para accionarla. El control de salidas queda exclusivamente en el controlador fail-safe.
- **FR-005**: En esta fase la API MUST NOT ofrecer ninguna operación de forzado manual, boost
  ni anulación del plan.
- **FR-006**: La dirección y el puerto de escucha MUST ser configurables, con un valor por
  defecto que no exponga el servicio más allá de lo necesario.

**Autenticación**

- **FR-007**: Toda operación de la API MUST exigir una credencial compartida, obtenida de una
  variable de entorno nombrada, servida por el mismo mecanismo protegido que ya sirve los
  demás secretos del despliegue.
- **FR-008**: La credencial MUST NOT almacenarse en la base de datos, en el repositorio ni en
  los logs, y MUST NOT aparecer en ninguna respuesta de la API.
- **FR-009**: Una petición sin credencial o con credencial incorrecta MUST rechazarse sin
  ejecutar la operación, y MUST NOT revelar en qué se diferencia de la correcta ni si la
  instalación existe.
- **FR-010**: La comparación de la credencial MUST NOT permitir deducirla observando el tiempo
  de respuesta.
- **FR-011**: El arranque MUST fallar con un mensaje accionable cuando la credencial no esté
  configurada, esté vacía o sea un valor de ejemplo evidente, y la API MUST NOT quedar
  escuchando en ese caso.
- **FR-012**: Los intentos rechazados MUST registrarse sin incluir el valor de la credencial
  ofrecida.

**Estado actual y vigencia**

- **FR-013**: La API MUST ofrecer una operación que devuelva el estado actual: acumuladores
  activos, potencia instantánea total, porcentaje del límite configurado, plan en curso con su
  ventana e intervalos, previsión utilizada con su origen, y minutos solicitados, asignados y
  no atendidos por acumulador.
- **FR-014**: El controlador MUST publicar periódicamente una señal de vida con su instante,
  su estado de degradación y el plan que está ejecutando.
- **FR-015**: La API MUST marcar el estado de las salidas como **no vigente** cuando la última
  señal de vida sea más antigua que una tolerancia configurable, y MUST indicar desde cuándo no
  se ve al controlador.
- **FR-016**: Con el estado marcado como no vigente, la API MUST NOT afirmar que ningún
  acumulador esté activo; MUST presentar el dato como último estado conocido.
- **FR-017**: La API MUST distinguir tres situaciones del controlador: vivo y sano, vivo pero
  degradado, y no visto. Un controlador que nunca arrancó MUST distinguirse de uno que dejó de
  responder.
- **FR-018**: La recuperación del controlador MUST reflejarse en el estado sin intervención
  manual y sin reiniciar la API.
- **FR-019**: Una señal de vida con instante futuro o un salto del reloj del sistema MUST NOT
  producir un estado permanentemente vigente ni permanentemente caducado.
- **FR-020**: Una instalación sin ningún plan MUST reportarse explícitamente como tal, sin
  ningún acumulador activo.

**Configuración: lectura y edición**

- **FR-021**: La API MUST ofrecer la lectura de la configuración completa y de un acumulador
  concreto, incluyendo la revisión vigente de configuración.
- **FR-022**: La API MUST NOT devolver nunca la localización de la base de datos, sus
  credenciales, ni el valor de la clave del proveedor meteorológico; del proveedor MUST
  devolver únicamente el nombre de su variable de entorno.
- **FR-023**: La API MUST ofrecer la modificación de parámetros de la instalación y de cada
  acumulador, y el alta y la baja de acumuladores.
- **FR-024**: Toda edición por API MUST ofrecer las mismas garantías que la edición por línea
  de comandos: validación de la configuración completa resultante antes de aplicar,
  atomicidad, y rechazo completo sin cambios parciales.
- **FR-025**: La API MUST reutilizar la validación existente; MUST NOT reimplementar ni relajar
  ninguna regla de validación.
- **FR-026**: Cada edición MUST exigir la revisión sobre la que el cliente basó su cambio, y
  MUST rechazarla con un error distinguible cuando la revisión ya no sea la vigente.
- **FR-027**: Cada edición aplicada MUST devolver el campo modificado, su valor anterior, su
  valor nuevo y la revisión resultante.
- **FR-028**: La API MUST rechazar valores con aspecto de credencial o de cadena de conexión en
  cualquier campo de configuración.
- **FR-029**: Un campo o un acumulador inexistente MUST producir un error que enumere los
  nombres admitidos o los acumuladores existentes, sin modificar nada.
- **FR-030**: La baja de un acumulador MUST conservar su histórico.
- **FR-031**: Una edición MUST NOT alterar el plan en ejecución; MUST tomar efecto en el
  siguiente recálculo.

**Histórico**

- **FR-032**: La API MUST ofrecer la consulta del histórico de planes, previsiones y
  transiciones de salida, filtrable por rango temporal.
- **FR-033**: Las consultas de histórico MUST estar paginadas, con un tamaño de página por
  defecto acotado y un máximo que no se pueda superar; la respuesta MUST indicar si hay más
  resultados.
- **FR-034**: Los resultados MUST ordenarse del más reciente al más antiguo.
- **FR-035**: Un rango sin datos MUST devolver una página vacía, no un error. Un rango con el
  inicio posterior al fin MUST rechazarse indicando el problema.
- **FR-036**: El histórico de un acumulador ya eliminado MUST seguir siendo consultable.
- **FR-037**: La API MUST ofrecer la ejecución de la limpieza de retención, devolviendo el
  recuento de lo eliminado, y MUST NOT eliminar la configuración ni los planes vivos.

**Errores y robustez**

- **FR-038**: Una base de datos inaccesible MUST producir una respuesta de error clara e
  identificable, sin traza técnica, sin revelar la localización de la base de datos, y sin
  inventar ningún dato de estado.
- **FR-039**: Una configuración almacenada inválida o un esquema que la API no comprenda MUST
  reportarse con la corrección a aplicar, y MUST NOT ofrecerse ninguna operación de escritura
  en ese caso.
- **FR-040**: Ningún error MUST exponer detalles internos de implementación, rutas del sistema
  de ficheros ni fragmentos de la cadena de conexión.
- **FR-041**: La API MUST responder a toda petición en un tiempo acotado, sin quedar bloqueada
  indefinidamente esperando la base de datos.

**Documentación y consumo por navegador**

- **FR-042**: La API MUST publicar una descripción autodescriptiva de todas sus operaciones,
  parámetros, respuestas y errores, y esa descripción MUST coincidir con lo realmente servido.
- **FR-043**: La descripción MUST NOT contener secretos ni valores reales de la configuración.
- **FR-044**: La API MUST permitir de forma configurable que un cliente de navegador la
  consuma desde otro origen, con una configuración por defecto restrictiva.
- **FR-045**: En esta fase la API MUST NOT servir ficheros estáticos de interfaz; el frontend
  corresponde a una fase posterior.

**Plataforma y pruebas**

- **FR-046**: La dependencia del servidor MUST vivir en un extra opcional; el planificador y
  el modelo térmico MUST poder importarse y ejecutarse sin ella instalada.
- **FR-047**: La instalación en el dispositivo de despliegue MUST NOT requerir compilador ni
  herramientas de construcción nativas.
- **FR-048**: La suite de pruebas MUST poder ejecutarse completa sin red, sin base de datos
  remota, sin hardware y sin abrir ningún puerto real, y MUST cubrir explícitamente los
  caminos de fallo de autenticación, de vigencia del estado y de base de datos inaccesible.

**Despliegue**

- **FR-049**: El procedimiento de instalación y la definición del servicio MUST proporcionar la
  credencial y la localización de la base de datos por el mismo mecanismo protegido que ya
  sirve los secretos existentes.
- **FR-050**: La API MUST instalarse como un servicio propio, independiente del controlador, y
  su instalación MUST NOT arrancarlo ni habilitarlo automáticamente.
- **FR-051**: La documentación MUST describir cómo generar la credencial, cómo exponer la API
  en la red local y qué riesgos conlleva exponerla más allá.

### Key Entities

- **Estado actual**: la fotografía del momento. Agrupa el instante de la consulta, la salud del
  controlador, la vigencia del dato, los acumuladores activos, la potencia instantánea y su
  porcentaje del límite, el plan en curso y la previsión que lo originó.
- **Señal de vida del controlador**: la prueba de que el controlador sigue funcionando. Tiene
  instante, estado de degradación e identificación del plan en ejecución. Es lo que permite
  distinguir un estado vigente de uno obsoleto.
- **Vigencia**: la cualidad del estado de salidas de ser actual o no, derivada de la antigüedad
  de la señal de vida frente a una tolerancia configurable.
- **Credencial de acceso**: el secreto compartido que autoriza las operaciones. Vive fuera de la
  base de datos y nunca aparece en respuestas ni en registros.
- **Página de histórico**: un tramo acotado de resultados históricos, con indicación de si hay
  más y del rango temporal cubierto.
- **Resultado de edición**: lo que devuelve un cambio aplicado: campo, valor anterior, valor
  nuevo y revisión resultante.
- **Descripción de la API**: el catálogo de operaciones, parámetros, respuestas y errores,
  derivado de lo realmente servido.

Las entidades de configuración e histórico —instalación, acumulador, salida, perfil térmico,
previsión, plan, intervalo de plan y transición de salida— son las ya definidas en la fase
anterior y no se redefinen aquí.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un cliente obtiene, en una sola consulta, todo lo necesario para presentar el
  estado de la instalación: qué carga ahora, cuánta potencia, qué plan, qué previsión y qué
  quedó sin atender.
- **SC-002**: La API nunca presenta un estado de salidas obsoleto como si fuera actual: en toda
  situación en que el controlador no esté visible, el dato aparece marcado como no vigente.
- **SC-003**: Detener, reiniciar o hacer fallar la API no produce ningún cambio observable en el
  estado de las salidas ni en la ejecución del plan.
- **SC-004**: Ninguna operación de la API puede activar una salida: verificable porque ninguna
  ruta de la API tiene acceso al medio de accionarlas.
- **SC-005**: Ninguna operación se ejecuta sin la credencial correcta, y ninguna respuesta ni
  ningún registro contiene el valor de la credencial.
- **SC-006**: Un operador lleva la configuración de la instalación a su estado deseado usando
  solo la API, con los mismos rechazos y los mismos mensajes que obtendría por consola.
- **SC-007**: Dos clientes que editan a la vez nunca pierden un cambio en silencio: uno tiene
  éxito y el otro es informado del conflicto.
- **SC-008**: Un operador reconstruye cualquier noche del periodo retenido consultando solo la
  API, sin acceder al dispositivo.
- **SC-009**: Ninguna condición de fallo —sin credencial, base de datos inaccesible, esquema no
  comprendido, configuración inválida, controlador ausente— produce una traza técnica, un
  cuelgue o un dato inventado.
- **SC-010**: La descripción publicada por la API coincide con las operaciones realmente
  servidas, sin operaciones fantasma ni operaciones indocumentadas.
- **SC-011**: La API se instala en el dispositivo de despliegue sin compilador y su consumo de
  memoria en reposo deja margen suficiente para el controlador en la misma máquina.
- **SC-012**: La suite completa se ejecuta sin red, sin base de datos remota, sin hardware y sin
  abrir ningún puerto real.

## Assumptions

- La credencial es un único secreto compartido, sin usuarios ni roles. La instalación tiene un
  solo operador; distinguir varios usuarios requeriría almacenar identidades y queda fuera de
  alcance.
- La credencial se genera manualmente al instalar y se rota editando el fichero de entorno y
  reiniciando la API. No hay gestión de rotación automática ni caducidad.
- La API se expone en la red local. Exponerla a internet requeriría cifrado en tránsito y un
  proxy inverso, que quedan fuera de alcance y se documentan como riesgo.
- El cifrado en tránsito se delega a un proxy inverso si se necesita; la API sirve en claro en
  la red local.
- La tolerancia de la señal de vida se deriva del intervalo de sondeo del controlador, con
  margen suficiente para no marcar como ausente a un controlador simplemente ocupado.
- El estado de las salidas se deduce del histórico de transiciones y de la señal de vida. No se
  consulta el hardware: leer el estado eléctrico real es competencia del driver, y la API no
  tiene acceso a él por diseño.
- La frecuencia de consulta prevista es del orden de segundos, con un único cliente habitual.
  No se dimensiona para muchos clientes concurrentes ni para consultas de alta frecuencia.
- El histórico se devuelve tal como se registró, sin agregaciones ni series temporales
  precalculadas. Las gráficas las construye el cliente.
- La configuración de la propia API —dirección, puerto, tolerancia de vigencia, orígenes
  admitidos— se sirve por entorno y no por base de datos, porque debe estar disponible antes de
  poder leer la base de datos.
- Una única instalación por base de datos, como en la fase anterior.
