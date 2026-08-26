# Feature Specification: Panel web de estado, configuración e histórico

**Feature Branch**: `003-web-panel`

**Created**: 2026-08-26

**Status**: Draft

**Input**: User description: "Panel web en Angular para ver el estado, editar la configuración y consultar el histórico. Servido por nginx en la Raspberry Pi, que además hace de proxy hacia la API. Token guardado en sessionStorage. Tests unitarios con el ejecutor de Angular."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ver de un vistazo si la instalación está haciendo lo correcto (Priority: P1)

Quien opera la instalación abre el panel en el navegador —del ordenador o del móvil— y en una
sola pantalla ve qué acumuladores están cargando, cuánta potencia se consume frente al límite,
qué plan está en curso, qué previsión lo generó y cuántos minutos quedaron sin atender. La
pantalla se actualiza sola.

**Why this priority**: Es la razón de ser del panel y lo que se consulta a diario. Sin ella la
fase no entrega nada.

**Independent Test**: contra una API con un estado conocido, se abre el panel y se comprueba que
cada dato mostrado coincide con lo que la API devuelve.

**Acceptance Scenarios**:

1. **Given** una instalación con el controlador en marcha y un plan activo, **When** se abre el
   panel, **Then** se ven los acumuladores con su estado, la potencia instantánea y su
   porcentaje del límite, la ventana del plan y la previsión con su origen.
2. **Given** un plan que no cubre toda la carga solicitada, **When** se mira el panel, **Then**
   los minutos no atendidos aparecen de forma destacada y no enterrados.
3. **Given** el panel abierto, **When** transcurre el intervalo de refresco, **Then** los datos
   se actualizan sin que el operador haga nada y sin perder la posición de lectura.
4. **Given** una instalación sin ningún plan, **When** se mira el panel, **Then** se indica
   explícitamente que no hay plan en curso, en lugar de mostrar una pantalla vacía o ceros.
5. **Given** un teléfono móvil, **When** se abre el panel, **Then** la información principal es
   legible y utilizable sin desplazamiento horizontal.

---

### User Story 2 - No dejar que el panel mienta (Priority: P1)

La API distingue «esto está pasando ahora» de «esto es lo último que se supo». El panel es el
lugar donde esa distinción se puede perder: un indicador verde junto a un acumulador cuyo
estado nadie puede confirmar induce a creer que hay 2,8 kW circulando. El panel muestra la
diferencia de forma inequívoca, y cuando no hay prueba lo dice en lugar de rellenar el hueco.

**Why this priority**: Es la razón por la que la fase anterior distingue estado vigente de
último estado conocido. Si el panel colapsa esa distinción, todo ese trabajo se pierde en el
último metro, que es justo donde el operador toma decisiones.

**Independent Test**: se presenta al panel cada una de las cuatro situaciones del controlador y
se comprueba qué se muestra y qué no se afirma en cada caso.

**Acceptance Scenarios**:

1. **Given** un controlador vivo y sano, **When** se mira el panel, **Then** el estado de cada
   salida se presenta como actual, sin advertencias.
2. **Given** un controlador que no se ve desde hace más tiempo del tolerado, **When** se mira el
   panel, **Then** se avisa de forma visible de que el estado no es actual, se indica desde
   cuándo no se ve al controlador, y **ningún** acumulador se presenta como cargando ahora.
3. **Given** un estado no vigente, **When** se mira la potencia, **Then** no se muestra ninguna
   cifra de potencia instantánea: se indica que no puede confirmarse.
4. **Given** un estado no vigente con un último estado conocido de encendido, **When** se mira
   ese acumulador, **Then** el último valor conocido se presenta claramente etiquetado como
   pasado, con el instante en que cambió, y **no** con la misma apariencia que un estado actual.
5. **Given** un controlador que nunca arrancó, **When** se mira el panel, **Then** se distingue
   de un controlador que dejó de responder, y se orienta sobre qué comprobar.
6. **Given** un controlador vivo pero degradado, **When** se mira el panel, **Then** se avisa de
   la degradación sin ocultar que el estado sí es actual.
7. **Given** la API informando de que hay más de un controlador, **When** se mira el panel,
   **Then** se muestra una advertencia prominente que explique el riesgo, no una nota discreta.

---

### User Story 3 - Cambiar la configuración sin abrir una consola (Priority: P1)

Quien opera la instalación edita desde el navegador los parámetros de la instalación y de cada
acumulador, y añade o elimina acumuladores. Los rechazos de la API se muestran junto al campo
que los causó, no como un mensaje genérico. Si otra persona o pestaña ha escrito antes, se
avisa y se ofrece releer en lugar de sobrescribir en silencio.

**Why this priority**: Es lo que elimina la necesidad de acceder por consola a la Raspberry Pi
para operar la instalación, que es el objetivo del bloque completo.

**Independent Test**: se aplican cambios válidos e inválidos desde el panel y se comprueba qué
queda almacenado, qué se rechaza y cómo se presenta cada rechazo.

**Acceptance Scenarios**:

1. **Given** el panel de configuración, **When** se cambia un parámetro a un valor válido,
   **Then** el cambio se aplica, se confirma visiblemente y la vista refleja el valor nuevo.
2. **Given** un valor que la API rechaza por inválido, **When** se envía, **Then** el mensaje se
   muestra **junto al campo ofensor**, el valor anterior sigue visible, y nada se ha cambiado.
3. **Given** dos pestañas abiertas, **When** una escribe y después la otra intenta escribir sobre
   la revisión antigua, **Then** la segunda avisa de que la configuración cambió y ofrece releer
   antes de reintentar, sin sobrescribir.
4. **Given** un campo con consecuencias eléctricas —potencia máxima, pin, nivel activo—, **When**
   se va a cambiar, **Then** se pide una confirmación explícita que indique qué se va a cambiar.
5. **Given** un acumulador, **When** se pide eliminarlo, **Then** se pide confirmación y se
   advierte de que su histórico se conserva.
6. **Given** un valor con aspecto de credencial, **When** se envía, **Then** se muestra el motivo
   del rechazo y la indicación de que los secretos van por variable de entorno.
7. **Given** un formulario a medio rellenar, **When** se navega a otra vista, **Then** no se
   pierden los cambios sin aviso.

---

### User Story 4 - Entrar y salir del panel (Priority: P1)

El panel exige la credencial de la API. Quien opera la instalación la introduce una vez, sigue
trabajando al recargar la página, y puede cerrar sesión de forma explícita. La credencial no
queda almacenada indefinidamente en el equipo, y si deja de ser válida el panel lo dice y vuelve
a pedirla en lugar de mostrar errores sin explicación.

**Why this priority**: Sin credencial no funciona ninguna otra vista, así que es prerrequisito de
todo lo demás.

**Independent Test**: se recorre el ciclo completo —sin credencial, con una incorrecta, con la
correcta, recarga, cierre de sesión— comprobando qué se muestra y qué se almacena.

**Acceptance Scenarios**:

1. **Given** un panel recién abierto sin credencial, **When** se carga, **Then** se pide la
   credencial y no se muestra ningún dato de la instalación.
2. **Given** una credencial incorrecta, **When** se envía, **Then** se indica que no es válida sin
   dar pistas sobre en qué se diferencia de la correcta.
3. **Given** una credencial correcta, **When** se envía, **Then** se accede al panel y la
   credencial sobrevive a recargar la página.
4. **Given** una sesión iniciada, **When** se cierra la pestaña y se abre otra, **Then** se vuelve
   a pedir la credencial: no queda almacenada de forma persistente.
5. **Given** una sesión iniciada, **When** se pulsa cerrar sesión, **Then** la credencial se borra
   del navegador y se vuelve a la pantalla de acceso.
6. **Given** una credencial que ha dejado de ser válida —por rotación en el servidor—, **When** se
   hace cualquier operación, **Then** se explica que hay que volver a introducirla y se vuelve a
   la pantalla de acceso, sin mostrar un error técnico.
7. **Given** cualquier situación, **When** se inspecciona lo que el panel escribe en el navegador,
   **Then** la credencial no aparece en ningún almacenamiento persistente ni en la dirección de
   la página.

---

### User Story 5 - Auditar el pasado desde el navegador (Priority: P2)

Quien opera la instalación consulta el histórico de planes, previsiones y transiciones en tablas
paginadas, filtrando por fechas y por acumulador. Puede reconstruir cualquier noche del periodo
retenido sin acceder al dispositivo.

**Why this priority**: es lo que hace auditable el sistema desde fuera, pero el estado y la
configuración se usan a diario y el histórico ocasionalmente.

**Independent Test**: con un histórico conocido se recorren las tablas, se filtra y se pagina,
comprobando qué se muestra y cómo se navega.

**Acceptance Scenarios**:

1. **Given** un histórico de varias noches, **When** se abre la vista de planes, **Then** se
   muestran los más recientes primero, paginados, con indicación de si hay más.
2. **Given** una página de resultados, **When** se pide la siguiente, **Then** se continúa sin
   repetir ni saltarse elementos.
3. **Given** un filtro de fechas, **When** se aplica, **Then** solo se muestran los registros del
   rango, y un rango sin datos se presenta como vacío y no como error.
4. **Given** un rango con el inicio posterior al fin, **When** se aplica, **Then** se avisa antes
   de consultar o se muestra el motivo del rechazo.
5. **Given** un acumulador ya eliminado de la configuración, **When** se consulta su histórico,
   **Then** sus transiciones siguen apareciendo, indicando que ya no existe en la configuración.
6. **Given** una previsión que vino del valor de reserva, **When** se mira el histórico, **Then**
   se distingue de una que vino del proveedor real.

---

### User Story 6 - Instalarlo y servirlo en la Raspberry Pi (Priority: P1)

Quien despliega compila el panel **fuera** del dispositivo y copia el resultado. En la Pi, un
servidor web sirve esos ficheros y hace de intermediario hacia la API, de modo que el navegador
ve un único origen y la API no necesita exponerse en la red. El procedimiento queda documentado,
incluida la vía para añadir cifrado.

**Why this priority**: sin esto el panel no llega al dispositivo, y compilar en la Pi no es una
opción viable.

**Independent Test**: se sigue el procedimiento documentado sobre una instalación limpia y se
comprueba que el panel carga y opera contra la API.

**Acceptance Scenarios**:

1. **Given** una máquina de desarrollo o un sistema de integración, **When** se compila el panel,
   **Then** se obtiene un conjunto de ficheros estáticos listos para copiar, sin necesidad de
   ninguna herramienta de construcción en el dispositivo.
2. **Given** el dispositivo con el servidor web configurado, **When** se abre el panel desde otro
   equipo de la red local, **Then** carga y opera contra la API sin configurar orígenes cruzados.
3. **Given** ese despliegue, **When** se comprueba la API, **Then** sigue escuchando únicamente en
   la interfaz local del dispositivo: el servidor web es el único componente expuesto.
4. **Given** el procedimiento documentado, **When** se lee, **Then** explica cómo añadir cifrado
   en tránsito y advierte de qué ocurre si no se añade.
5. **Given** una actualización del panel, **When** se despliega la versión nueva, **Then** el
   navegador obtiene los ficheros nuevos y no una versión antigua en caché.
6. **Given** el panel servido, **When** se navega directamente a una dirección interna del panel
   y se recarga, **Then** carga correctamente en lugar de dar un error de página no encontrada.

---

### Edge Cases

- La API no responde: el panel lo indica y conserva lo último que mostró, claramente marcado
  como no actual, en lugar de vaciarse o quedarse cargando indefinidamente.
- La API responde que su base de datos no está disponible: se muestra el motivo y qué comprobar,
  sin traza técnica.
- La API responde que el esquema necesita migración: se indica que hay que actuar en el
  dispositivo y qué comando ejecutar, dejando claro que el panel no puede hacerlo.
- La instalación no tiene ningún acumulador: las vistas siguen siendo utilizables y lo indican.
- La pestaña queda en segundo plano muchas horas: el refresco no consume recursos del dispositivo
  inútilmente, y al volver al frente los datos se actualizan de inmediato.
- Se pierde la conectividad de red a mitad de una edición: se informa de que no se pudo aplicar y
  el formulario conserva lo introducido.
- El reloj del equipo que muestra el panel no coincide con el del dispositivo: las antigüedades
  se presentan usando los instantes que da la API, no calculadas contra el reloj local, para no
  mostrar edades imposibles.
- Se abre el panel en una pantalla estrecha mientras se edita una tabla ancha: la tabla se puede
  recorrer sin romper la página.
- El histórico está vacío porque la retención acaba de limpiarlo: se presenta como vacío.

## Requirements *(mandatory)*

### Functional Requirements

**Acceso y credencial**

- **FR-001**: El panel MUST exigir la credencial de la API antes de mostrar cualquier dato de la
  instalación.
- **FR-002**: La credencial MUST conservarse de forma que sobreviva a recargar la página y
  MUST NOT persistir tras cerrar la pestaña o la ventana.
- **FR-003**: La credencial MUST NOT aparecer nunca en la dirección de la página, en el
  histórico de navegación, ni en ningún almacenamiento persistente del navegador.
- **FR-004**: Una credencial rechazada MUST informar de que no es válida y MUST NOT revelar en
  qué se diferencia de la correcta.
- **FR-005**: El panel MUST ofrecer cierre de sesión explícito que borre la credencial del
  navegador.
- **FR-006**: Cuando la API rechace la credencial durante el uso, el panel MUST volver a la
  pantalla de acceso explicando que hay que introducirla de nuevo, y MUST NOT mostrar un error
  técnico.

**Estado, y honestidad sobre él**

- **FR-007**: El panel MUST mostrar en una sola vista: acumuladores con su estado, potencia
  instantánea y su porcentaje del límite, plan en curso con su ventana, previsión utilizada con
  su origen, y minutos solicitados, asignados y no atendidos por acumulador.
- **FR-008**: El panel MUST refrescar el estado periódicamente sin intervención del operador, y
  MUST NOT perder la posición de lectura ni el foco al refrescar.
- **FR-009**: Cuando la API indique que el estado **no es vigente**, el panel MUST mostrar un
  aviso visible, MUST indicar desde cuándo no se ve al controlador, y MUST NOT presentar ningún
  acumulador como cargando en ese momento.
- **FR-010**: Con el estado no vigente, el panel MUST NOT mostrar ninguna cifra de potencia
  instantánea.
- **FR-011**: El panel MUST distinguir visualmente tres cosas que **no** pueden compartir
  apariencia: salida encendida y confirmada, salida apagada y confirmada, y estado sin
  confirmar. Un valor sin confirmar MUST presentarse etiquetado como pasado, con el instante en
  que cambió.
- **FR-012**: El panel MUST distinguir las cuatro situaciones del controlador que informa la API
  —sano, degradado, silencioso y nunca visto— y MUST orientar sobre qué comprobar en cada caso
  anómalo.
- **FR-013**: Cuando la API informe de la sospecha de más de un controlador, el panel MUST
  mostrar una advertencia prominente que explique el riesgo eléctrico.
- **FR-014**: Una instalación sin plan en curso MUST indicarse explícitamente, y MUST NOT
  representarse con valores a cero ni con una vista vacía.
- **FR-015**: Los minutos no atendidos MUST mostrarse de forma destacada cuando existan.
- **FR-016**: Las antigüedades MUST derivarse de los instantes que proporciona la API y MUST NOT
  calcularse contra el reloj del equipo que muestra el panel.

**Configuración**

- **FR-017**: El panel MUST permitir leer y modificar los parámetros de la instalación, del
  proveedor meteorológico y de cada acumulador, y añadir y eliminar acumuladores.
- **FR-018**: Todo rechazo de la API MUST mostrarse junto al campo que lo causó cuando la API
  identifique un campo, y MUST NOT reducirse a un mensaje genérico.
- **FR-019**: El panel MUST enviar en cada escritura la revisión que leyó, y ante un conflicto
  MUST avisar de que la configuración cambió y ofrecer releer, sin sobrescribir.
- **FR-020**: Los campos con consecuencias eléctricas —potencia máxima simultánea, asignación de
  pin y nivel activo— MUST exigir una confirmación explícita que indique qué se va a cambiar.
- **FR-021**: La eliminación de un acumulador MUST exigir confirmación e informar de que su
  histórico se conserva.
- **FR-022**: Un formulario con cambios sin guardar MUST advertir antes de descartarlos.
- **FR-023**: El panel MUST NOT reimplementar ni relajar ninguna validación de la API: valida
  para dar respuesta inmediata, y la API sigue siendo la autoridad.

**Histórico**

- **FR-024**: El panel MUST permitir consultar planes, previsiones y transiciones en tablas
  paginadas, con los más recientes primero.
- **FR-025**: El panel MUST permitir filtrar por rango de fechas y, en transiciones, por
  acumulador.
- **FR-026**: La navegación entre páginas MUST usar el mecanismo de continuación de la API, sin
  repetir ni omitir elementos.
- **FR-027**: Un rango sin datos MUST presentarse como vacío y MUST NOT como error. Un rango
  invertido MUST avisarse.
- **FR-028**: El histórico de un acumulador que ya no está en la configuración MUST seguir siendo
  consultable, indicando esa circunstancia.
- **FR-029**: El origen de cada previsión MUST distinguirse, en particular si vino del valor de
  reserva.

**Errores y ausencias**

- **FR-030**: Cuando la API no responda, el panel MUST indicarlo, MUST conservar lo último
  mostrado marcado como no actual, y MUST NOT quedarse cargando indefinidamente ni vaciarse.
- **FR-031**: Cada condición de error que informa la API MUST traducirse a una explicación
  accionable, sin trazas técnicas.
- **FR-032**: Cuando la API informe de que el esquema necesita intervención, el panel MUST indicar
  que hay que actuar en el dispositivo y qué ejecutar, y MUST dejar claro que el panel no puede
  hacerlo.
- **FR-033**: Una edición que falle por pérdida de conectividad MUST informar de que no se aplicó
  y MUST conservar lo introducido en el formulario.

**Presentación**

- **FR-034**: La información principal MUST ser legible y utilizable en la pantalla de un
  teléfono, sin desplazamiento horizontal de la página.
- **FR-035**: Las tablas anchas MUST poder recorrerse sin romper la disposición de la página.
- **FR-036**: La distinción entre estado confirmado y sin confirmar MUST NOT depender únicamente
  del color, para que siga siendo perceptible sin distinguir colores.

**Despliegue**

- **FR-037**: El panel MUST compilarse fuera del dispositivo de despliegue, y su instalación en
  el dispositivo MUST NOT requerir ninguna herramienta de construcción allí.
- **FR-038**: En el dispositivo, un servidor web MUST servir los ficheros del panel y MUST actuar
  de intermediario hacia la API, de modo que el navegador vea un único origen.
- **FR-039**: Con ese despliegue, la API MUST seguir escuchando únicamente en la interfaz local
  del dispositivo, y MUST NOT ser necesario configurar orígenes cruzados.
- **FR-040**: La navegación directa a cualquier dirección interna del panel MUST cargar
  correctamente al recargar la página.
- **FR-041**: El despliegue de una versión nueva MUST hacer que el navegador obtenga los ficheros
  nuevos y MUST NOT servir una versión antigua desde la caché.
- **FR-042**: La documentación MUST describir el procedimiento completo de compilación y
  despliegue, cómo añadir cifrado en tránsito, y qué riesgo se asume si no se añade.
- **FR-043**: La instalación del panel MUST NOT arrancar ni habilitar automáticamente ningún
  servicio nuevo.

**Pruebas y consumo**

- **FR-044**: La lógica de presentación del estado —en particular la interpretación de un estado
  sin confirmar— MUST tener cobertura de pruebas automatizadas.
- **FR-045**: Las pruebas del panel MUST poder ejecutarse sin red, sin la API real y sin
  hardware.
- **FR-046**: El refresco periódico MUST reducirse o detenerse cuando la vista no esté visible, y
  MUST reanudarse de inmediato al volver al frente.
- **FR-047**: La suite de pruebas existente del proyecto MUST seguir pasando sin cambios de
  comportamiento.

### Key Entities

- **Sesión**: la credencial en uso y su duración. Vive en el navegador mientras la pestaña está
  abierta y desaparece al cerrarla.
- **Vista de estado**: la proyección para pantalla de lo que devuelve la API, incluida la
  decisión de qué se puede afirmar y qué debe presentarse como pasado.
- **Indicador de salida**: la representación de un acumulador con **tres** estados posibles, no
  dos: encendido confirmado, apagado confirmado y sin confirmar.
- **Formulario de configuración**: los valores editables, la revisión sobre la que se basan, los
  cambios pendientes y los mensajes de rechazo asociados a cada campo.
- **Página de histórico**: un tramo de resultados con su filtro, su cursor de continuación y la
  indicación de si hay más.
- **Traducción de error**: la correspondencia entre cada condición que informa la API y la
  explicación accionable que se muestra.
- **Artefacto compilado**: el conjunto de ficheros estáticos que se despliega en el dispositivo.
- **Configuración del servidor web**: la que sirve los ficheros, actúa de intermediario hacia la
  API y controla el comportamiento de caché.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un operador ve el estado completo de su instalación en una sola pantalla, sin
  desplazarse ni navegar, tanto en ordenador como en teléfono.
- **SC-002**: El panel **nunca** presenta como actual un estado que la API marca como no vigente:
  en toda situación en que el controlador no esté visible, ninguna salida aparece como cargando y
  no se muestra potencia instantánea.
- **SC-003**: Un estado sin confirmar es distinguible de un estado confirmado sin depender del
  color.
- **SC-004**: Un operador lleva la configuración de su instalación al estado deseado usando solo
  el navegador, sin acceder por consola al dispositivo.
- **SC-005**: Ningún rechazo de la API llega al operador como mensaje genérico cuando la API
  identifica el campo ofensor.
- **SC-006**: Dos pestañas editando a la vez no pierden un cambio en silencio: una tiene éxito y
  la otra es informada y puede releer.
- **SC-007**: La credencial no queda en el equipo tras cerrar la pestaña, ni aparece en la
  dirección de la página en ningún momento.
- **SC-008**: Un operador reconstruye cualquier noche del periodo retenido navegando el histórico
  del panel.
- **SC-009**: Ninguna condición de fallo —API caída, base de datos inaccesible, esquema
  pendiente, credencial caducada, red perdida— produce una pantalla en blanco, una carga
  indefinida o una traza técnica.
- **SC-010**: El panel se despliega en el dispositivo copiando ficheros, sin ninguna herramienta
  de construcción allí, y la API sigue sin estar expuesta en la red.
- **SC-011**: Tras desplegar una versión nueva, el navegador la obtiene sin borrar la caché a
  mano.
- **SC-012**: Las pruebas del panel se ejecutan sin red ni API real, y cubren la interpretación
  del estado sin confirmar.
- **SC-013**: La suite existente del proyecto sigue pasando íntegra.

## Assumptions

- El panel consume exclusivamente la API de la fase anterior y no accede a la base de datos ni a
  ninguna otra fuente.
- El panel no puede accionar salidas, porque la API no lo permite. No hay forzado manual en esta
  fase, y el panel no debe sugerir que exista.
- Un solo operador y una sola credencial compartida, como en la fase anterior. Sin usuarios,
  roles ni permisos diferenciados.
- El cifrado en tránsito se delega al servidor web del dispositivo y queda documentado como paso
  opcional; el panel funciona igual con o sin él.
- El panel se usa en una red local de confianza. Publicarlo en internet exige cifrado y queda
  fuera de alcance.
- Los navegadores objetivo son versiones actuales de los principales navegadores de escritorio y
  móvil. No se da soporte a navegadores heredados.
- La cadencia de refresco por defecto se elige del orden de segundos, coherente con el sondeo del
  controlador, y es ajustable.
- Sin gráficas ni series temporales en esta fase: el histórico se presenta en tablas. La API no
  precalcula agregaciones.
- Sin traducción a varios idiomas en esta fase; la interfaz se redacta en un solo idioma.
- Sin instalación como aplicación ni funcionamiento sin conexión: es una página que necesita la
  API para tener sentido.
