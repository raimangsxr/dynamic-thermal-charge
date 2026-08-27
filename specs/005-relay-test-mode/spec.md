# Feature Specification: Prueba manual de relés

**Feature Branch**: `005-relay-test-mode`

**Created**: 2026-08-27

**Status**: Approved

**Input**: User description: "Poder lanzar pruebas de relés desde el frontend. La Raspberry Pi opera los relés de los acumuladores mediante señales digitales GPIO; desde el frontend se debe poder entrar en modo test y activar/desactivar cualquier acumulador configurado, activando/desactivando los GPIO correspondientes. La interfaz debe mostrar los acumuladores de forma ordenada y amigable."

## Clarifications

### Session 2026-08-27

- Q: ¿Quién puede operar una sesión de prueba cuando hay varias personas autenticadas en el panel? → A: Únicamente el cliente o pestaña que conserva la credencial de sesión puede accionar relés, renovar o finalizar la sesión; no se infiere una identidad humana.
- Q: ¿Qué ocurre si falla parcialmente el apagado de seguridad? → A: Se activa un *fault latch* persistente que mantiene suspendido el automático hasta que un barrido OFF posterior queda confirmado o verificado para todas las salidas y se publica la recuperación operativa.
- Q: ¿Debe un fallo de auditoría impedir una conmutación de seguridad? → A: No; la auditoría se intenta siempre y el fallo se muestra como estado degradado, pero nunca bloquea la conmutación de seguridad.
- Q: ¿Cómo se recupera el resultado después de que una sesión termine? → A: Mediante una consulta terminal recuperable por `session_id`, que conserva el estado terminal, el motivo de finalización y el resultado confirmado o no confirmable de cada salida.
- Q: ¿Cómo se separan el sondeo de estado y la renovación de la concesión? → A: El panel sondea el estado cada 1 s mientras espera cambios; renueva el lease cada 5 s solo si la pestaña propietaria está visible.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Probar un acumulador desde el panel (Priority: P1)

Quien opera la instalación entra de forma explícita en un modo de prueba temporal desde el
panel y puede activar o desactivar cada acumulador que esté configurado. La acción produce el
estado físico solicitado para el relé de ese acumulador, permitiendo comprobar el cableado y el
funcionamiento sin acceder a la Raspberry Pi.

**Why this priority**: comprobar un relé individual es el objetivo central de la feature y
reduce la necesidad de realizar pruebas eléctricas desde una consola o directamente en el
dispositivo.

**Independent Test**: con una instalación configurada y un controlador disponible, se entra en
modo de prueba, se activa y desactiva un acumulador, y se comprueba que el estado informado y el
estado físico del relé cambian de acuerdo con cada orden.

**Acceptance Scenarios**:

1. **Given** una persona autenticada, un controlador disponible y al menos un acumulador
   configurado, **When** entra en modo de prueba, **Then** el panel indica inequívocamente que
   las órdenes manuales están habilitadas y que el control automático no gobierna las salidas
   mientras dure ese modo.
2. **Given** el modo de prueba activo y un acumulador configurado apagado, **When** la persona
   solicita activarlo, **Then** se activa únicamente el relé asociado a ese acumulador y el
   panel confirma su estado actual.
3. **Given** el modo de prueba activo y un acumulador configurado activo, **When** la persona
   solicita desactivarlo, **Then** se desactiva su relé y el panel confirma su estado actual.
4. **Given** el modo de prueba activo, **When** se solicita actuar sobre cada uno de varios
   acumuladores configurados, **Then** cada orden afecta al acumulador seleccionado y nunca a
   otro distinto.
5. **Given** el modo de prueba no está activo, **When** se intenta activar o desactivar un
   acumulador desde el panel, **Then** la orden no se ejecuta y el panel explica que primero hay
   que entrar en modo de prueba.

---

### User Story 2 - Ver y terminar una prueba con seguridad (Priority: P1)

Quien opera la instalación puede saber en todo momento si hay una prueba en curso y qué
acumuladores se encuentran activos manualmente. Al terminar la prueba, todas las salidas quedan
en estado seguro antes de que el funcionamiento normal pueda continuar.

**Why this priority**: las pruebas accionan cargas eléctricas reales; evitar una salida activa
por accidente al acabar, perder conectividad o perder el control es tan importante como poder
encenderla intencionadamente.

**Independent Test**: se activa uno o más acumuladores durante una prueba, se abandona el modo,
y se comprueba que todos quedan apagados y que el panel deja de presentarlos como controlados
manualmente.

**Acceptance Scenarios**:

1. **Given** el modo de prueba activo, **When** se consulta el panel, **Then** se muestra qué
   acumuladores están activos manualmente, cuáles están apagados y cómo finalizar la prueba.
2. **Given** uno o más acumuladores activos en modo de prueba, **When** la persona finaliza el
   modo, **Then** todas las salidas de acumuladores quedan apagadas antes de restaurar el
   funcionamiento automático.
3. **Given** el modo de prueba activo, **When** se pierde la comunicación con el controlador o
   no puede confirmarse el estado de una orden, **Then** el panel deja claro que el estado no se
   puede confirmar y no afirma que ninguna salida esté apagada o encendida.
4. **Given** una salida activa durante una prueba, **When** el controlador se detiene, se
   reinicia o detecta una condición de fallo, **Then** la salida se lleva al estado seguro de
   apagado y el modo de prueba no permanece activo sin control.
5. **Given** un barrido OFF de cierre falla en una o más salidas, **When** el controlador intenta
   recuperar la operación, **Then** activa un *fault latch* persistente, mantiene suspendido el
   automático y no lo reanuda hasta confirmar o verificar un barrido OFF completo, mostrando el
   estado de recuperación.
6. **Given** una sesión termina mientras el panel pierde conectividad o se recarga, **When** se
   consulta posteriormente su `session_id`, **Then** se recuperan su estado terminal, motivo de
   finalización y los resultados confirmados o no confirmables de sus salidas.

---

### User Story 3 - Encontrar el acumulador correcto (Priority: P2)

Quien realiza una prueba ve los acumuladores configurados en una presentación ordenada,
comprensible y utilizable tanto en pantalla ancha como estrecha. Cada control identifica
claramente el acumulador sobre el que actuará y diferencia el estado manual de la información
histórica o no confirmada.

**Why this priority**: la prueba se usa para identificar cableado y relés; una interfaz confusa
puede llevar a accionar el acumulador equivocado.

**Independent Test**: con varios acumuladores de nombres y estados distintos, se abre la vista
de prueba y se comprueba que se pueden identificar, recorrer y accionar sin confundir los
controles.

**Acceptance Scenarios**:

1. **Given** varios acumuladores configurados, **When** se abre la vista de prueba, **Then** se
   muestran en un orden estable y cada uno conserva el nombre con el que se configuró.
2. **Given** la vista de prueba, **When** se observa un acumulador, **Then** su control de
   activación o desactivación está asociado de forma inequívoca a su nombre y estado.
3. **Given** una pantalla estrecha, **When** se usa la vista de prueba, **Then** se pueden leer
   y accionar todos los acumuladores sin desplazamiento horizontal para los controles
   principales.
4. **Given** una instalación sin acumuladores configurados, **When** se abre la vista de prueba,
   **Then** se informa de ello y no se ofrecen controles manuales sin destino.

### Edge Cases

- La instalación alcanza o alcanzaría un límite eléctrico seguro con las salidas ya activas:
  la acción que no pueda realizarse se rechaza, se explica el motivo y no cambia el estado de
  los demás acumuladores.
- Se solicita actuar sobre un acumulador que fue eliminado o dejó de estar disponible después
  de abrir la vista: no se acciona ninguna salida y se pide actualizar la información mostrada.
- La persona solicita la misma transición que ya está confirmada —activar uno activo o apagar
  uno apagado—: el resultado confirma el estado existente sin afectar a otros acumuladores.
- La sesión deja de ser válida durante una prueba: no se acepta ninguna nueva orden y la prueba
  debe finalizar en el estado seguro definido.
- Una orden manual se rechaza o falla: el panel muestra un mensaje comprensible y refleja solo
  el último estado que pueda confirmarse.
- Falla el registro de auditoría de una acción: se intenta registrarlo, el sistema expone el
  estado degradado y la conmutación de seguridad continúa sin esperar a que la auditoría se
  recupere.
- Un barrido OFF falla parcialmente: el sistema conserva un *fault latch* persistente, no devuelve
  el gobierno al automático y comunica la recuperación solo tras un barrido OFF completo
  confirmado o verificado.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: El sistema MUST permitir únicamente a personas autenticadas entrar y salir de un
  modo de prueba explícito desde el panel.
- **FR-002**: El sistema MUST mostrar de forma prominente mientras esté activo el modo de prueba,
  que las salidas se están gobernando manualmente y cómo terminarlo.
- **FR-003**: El sistema MUST permitir activar y desactivar individualmente cualquier acumulador
  que figure en la configuración vigente, solo mientras el modo de prueba esté activo.
- **FR-004**: Cada orden manual aceptada MUST afectar exclusivamente al relé del acumulador
  seleccionado y MUST informar si el estado resultante pudo confirmarse.
- **FR-005**: El sistema MUST impedir que el control automático active o desactive acumuladores
  mientras el modo de prueba esté activo.
- **FR-006**: Al finalizar el modo de prueba, el sistema MUST apagar todos los relés de
  acumuladores antes de permitir que el control automático vuelva a gobernarlos.
- **FR-007**: El sistema MUST llevar todas las salidas de acumuladores al estado seguro apagado
  si una prueba no puede continuar de forma controlada, incluido al detenerse, reiniciarse o
  fallar el controlador.
- **FR-008**: El sistema MUST impedir una orden de prueba cuando no pueda verificar que el
  controlador está disponible para ejecutarla, y MUST comunicar la situación sin presentar un
  estado físico no confirmado como actual.
- **FR-009**: El sistema MUST respetar los límites eléctricos seguros de la instalación durante
  las pruebas y rechazar una orden que los exceda sin alterar las demás salidas.
- **FR-010**: El panel MUST presentar todos los acumuladores configurados en un orden estable,
  usando su nombre configurado y un estado legible para cada uno.
- **FR-011**: El panel MUST asociar sin ambigüedad cada control de activación y desactivación con
  el acumulador al que afecta, y MUST conservar esa usabilidad en pantallas estrechas.
- **FR-012**: El sistema MUST registrar cada entrada y salida del modo de prueba y cada cambio de
  estado de salida realizado durante una prueba, con el acumulador afectado, el resultado y el
  instante.
- **FR-013**: El sistema MUST rechazar sin accionar ninguna salida las órdenes dirigidas a
  acumuladores que no estén en la configuración vigente.
- **FR-014**: Durante una sesión de prueba, únicamente el cliente o pestaña que conserva la
  credencial de sesión MUST poder accionar relés, renovar o finalizar la sesión; el sistema MUST
  rechazar las solicitudes sin esa credencial sin accionar salidas y MUST NOT inferir ni ampliar
  una identidad humana.
- **FR-015**: Si un barrido OFF falla parcialmente, el sistema MUST activar un *fault latch*
  persistente, mantener suspendido el control automático y no reanudarlo hasta que un barrido OFF
  posterior quede confirmado o verificado para todas las salidas; el estado de recuperación MUST
  ser observable.
- **FR-016**: El sistema MUST intentar registrar la auditoría de cada entrada, salida, orden y
  resultado de prueba. Si el almacenamiento de auditoría falla, MUST exponer un estado degradado,
  pero MUST NOT bloquear ni retrasar una conmutación de seguridad.
- **FR-017**: El sistema MUST permitir recuperar por `session_id` el resultado de una sesión
  terminal, incluido su estado, motivo de finalización y el estado confirmado o no confirmable de
  cada salida.
- **FR-018**: Mientras una sesión esté en curso o tenga cambios pendientes, el panel MUST sondear
  su estado cada 1 s. La renovación del lease MUST ser una operación separada, cada 5 s y solo
  desde una pestaña propietaria visible.

### Key Entities *(include if feature involves data)*

- **Sesión de prueba**: periodo temporal de control manual, con su estado, instante de inicio y
  el motivo o instante de finalización.
- **Estado de prueba de acumulador**: estado manual solicitado y estado confirmado del relé de
  un acumulador configurado durante una sesión de prueba.
- **Registro de prueba**: evidencia consultable de una entrada, salida u orden de prueba, con su
  resultado, acumulador afectado cuando corresponda e instante.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Una persona autenticada puede iniciar una prueba, activar un acumulador
  configurado, confirmar su resultado y desactivarlo en menos de 30 segundos, sin acceso a la
  Raspberry Pi.
- **SC-002**: El 100 % de las órdenes aceptadas en una prueba afectan solamente al acumulador
  seleccionado y su resultado queda visible para quien la inició.
- **SC-003**: El 100 % de los fallos parciales de apagado detectados durante una prueba activan un
  *fault latch* persistente; el automático permanece suspendido hasta que un barrido OFF completo
  queda confirmado o verificado y se informa la recuperación operativa.
- **SC-004**: Con una instalación de hasta 20 acumuladores configurados, todos se pueden
  identificar y accionar desde la vista de prueba sin confundir el control de un acumulador con
  el de otro.
- **SC-005**: Con el almacenamiento de auditoría sano, el 100 % de las entradas, salidas y
  cambios de salida realizados durante una prueba quedan registrados con resultado e instante.
  Ante un fallo aislado de auditoría, el estado degradado queda visible sin bloquear la
  conmutación de seguridad.

## Assumptions

- Se reutiliza la autenticación ya exigida por el panel; la feature no crea nuevos tipos de
  usuarios ni permisos diferenciados. La credencial de sesión identifica operativamente al
  cliente o pestaña que la conserva, sin representar ni ampliar una identidad humana.
- «Modo test» significa control manual temporal, exclusivo del control automático: no se
  reinterpretan ni modifican la configuración ni el plan de carga existentes.
- Al salir del modo de prueba, y ante cualquier pérdida de control, apagar todas las salidas es
  preferible a conservar una salida manualmente activa; el control normal podrá recomenzar solo
  después.
- El límite eléctrico seguro configurado para la instalación también se aplica a las pruebas
  manuales.
- El orden estable por defecto será el orden de los acumuladores definido en la configuración;
  si no existe, se mostrará por nombre.
- El sondeo de estado y la renovación de lease tienen finalidades distintas: el primero permite
  reflejar confirmaciones rápidamente y el segundo mantiene la sesión viva solo mientras su
  pestaña propietaria permanece visible.
- Esta fase cubre la prueba de acumuladores configurados desde el panel existente. No incluye
  editar su configuración, probar salidas sin acumulador, ni crear automatizaciones externas.
