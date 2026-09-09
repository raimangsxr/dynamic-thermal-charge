## Purpose

Garantizar que la planificación automática solo publica decisiones reproducibles
y ejecutables a partir de previsión y telemetría aptas.

## Requirements

### Requirement: Modelo acoplado de energía y confort por habitación

Cada acumulador debe modelar la energía almacenada y la temperatura interior
por intervalo. La capacidad del acumulador es la potencia nominal multiplicada
por sus horas de carga completa; la energía inicial es el SOC recibido por esa
capacidad. Para un intervalo de `dt` horas, el intercambio firmado del recinto
es `K_room * (T_inside - T_outside) * dt` y la temperatura siguiente cumple
`T_next = T_inside + (E_heater - E_loss) / C_room`. La energía almacenada debe
permanecer entre cero y la capacidad, y la carga nominal solo se suma cuando el
acumulador está encendido.

Cuando una consigna está activa en un slot, la temperatura objetivo es una
invariante en sus dos bordes: se evalúan tanto `T_inside` al inicio como
`T_next` al final. El optimizador puede usar slots anteriores sin consigna para
precalentar, pero un déficit en cualquiera de esos bordes conserva el plan como
`DEGRADED` y registra el instante y el déficit proyectado.

#### Scenario: Exterior más cálido que el interior

- **WHEN** la temperatura exterior supera la interior durante un intervalo
- **THEN** el intercambio térmico es negativo, aumenta la temperatura
  proyectada y se conserva el balance energético firmado

### Requirement: Consignas semanales y fuente del objetivo

Cada acumulador habilitado debe tener una o más consignas semanales de
temperatura, intervalo horario local, días de la semana y estado activo. El
inicio del intervalo se incluye y el fin se excluye; un intervalo cuyo fin es
anterior al inicio continúa en el día natural siguiente. La planificación usa
la consigna solo mientras el instante pertenece a un intervalo activo, no
mantiene una consigna durante los huecos y nunca usa telemetría de temperatura
del acumulador ni deriva una temperatura desde el SOC. Los intervalos de un
mismo acumulador no pueden solaparse, incluso al cruzar medianoche.

#### Scenario: Intervalo activo durante la semana

- **WHEN** llega una hora local incluida entre el inicio y el fin de una regla
- **THEN** ese intervalo usa la temperatura objetivo y deja de usarla en su fin
  exclusivo, también si la regla cruza medianoche

#### Scenario: Hueco sin consigna

- **WHEN** un intervalo de planificación queda fuera de todas las reglas activas
- **THEN** no tiene objetivo térmico ni déficit de confort

#### Scenario: Precalentamiento antes de una consigna

- **WHEN** una consigna comienza en el siguiente slot y la temperatura medida está
  por debajo del objetivo
- **THEN** el plan puede cargar y entregar calor en slots anteriores para alcanzar
  el objetivo en el borde inicial y mantenerlo en el borde final del primer slot
  activo

#### Scenario: Fin exclusivo de una consigna

- **WHEN** una consigna termina exactamente en un límite de slot
- **THEN** se comprueba el objetivo en el borde final del último slot activo y no
  se exige en el slot posterior salvo que otra regla esté activa

#### Scenario: Déficit al comienzo del horizonte

- **WHEN** una consigna está activa en el primer borde del horizonte y la
  temperatura medida está por debajo del objetivo
- **THEN** se conserva el déficit inicial con `at` igual al inicio del horizonte,
  aunque el plan consiga alcanzar el objetivo al terminar ese slot

#### Scenario: Solape de consignas

- **WHEN** dos reglas del mismo acumulador ocupan el mismo tramo de un día
- **THEN** la configuración se rechaza con el acumulador y las reglas
  identificados, sin guardar cambios parciales

### Requirement: Entradas físicas frescas y resultado explícito

La planificación automática requiere temperatura interior y SOC recientes para
cada acumulador habilitado. Si falta o está obsoleta cualquiera de esas
lecturas, falta una consigna, no hay cobertura meteorológica, los coeficientes
son inválidos o la configuración eléctrica es inviable, el resultado debe ser
explícitamente `INVALID` o `DEGRADED` con la causa; nunca debe volver al cálculo
basado en porcentajes.

#### Scenario: Telemetría incompleta

- **WHEN** un acumulador no tiene temperatura interior o SOC reciente
- **THEN** el resultado identifica la entrada ausente y no publica un plan
  automático basado en un valor supuesto

### Requirement: Auditoría física del plan

Las vistas previas, el plan activo, las explicaciones y el historial deben
conservar por acumulador e intervalo la temperatura interior proyectada y la
energía almacenada en los bordes de inicio y fin, la consigna, el SOC, el calor
entregado, el intercambio térmico y los déficits de temperatura de ambos bordes
cuando existan. La capacidad total en kWh debe estar disponible para expresar el
SOC relativo de cada acumulador.

#### Scenario: Consulta de un intervalo planificado

- **WHEN** el operador abre el detalle de un intervalo
- **THEN** puede distinguir los valores de inicio y fin de energía almacenada,
  carga, calor entregado, intercambio térmico, interior, objetivo y déficit sin
  inferir temperatura a partir del SOC

### Requirement: Ciclo de previsión AEMET durable

La consulta AEMET debe ejecutarse a la hora local configurada y conservar su
estado entre reinicios. Tras un fallo debe reintentar cinco veces, a intervalos
horarios; al agotarlos, debe conservar la última previsión AEMET válida como
obsoleta para recalcular, sin habilitar carga automática con previsiones de
respaldo o simuladas.

#### Scenario: Fallo de AEMET durante una replanificación

- **WHEN** falla una consulta AEMET programada
- **THEN** se persiste el intento, se programa el reintento correspondiente y
  la replanificación continúa con la última previsión almacenada apta

### Requirement: Integridad de la planificación automática

Un plan solo será `FEASIBLE` si todas las fases del solver alcanzan el óptimo y
todas sus variables necesarias tienen valor. Una solución factible verificada
al expirar el límite de tiempo será `DEGRADED` con la violación
`solver_time_limit`; una solución no verificable será `INVALID`.

#### Scenario: Límite de tiempo del solver

- **WHEN** el solver alcanza su límite de tiempo
- **THEN** el controlador no publica un plan factible salvo que la solución se
  haya verificado, y en tal caso informa `solver_time_limit`

### Requirement: Activación segura de previews completados

La activación debe poder reutilizar un preview durable completado cuando el
token de entrada vigente, las revisiones de configuración y objetivos térmicos
y el payload de consignas coinciden. En cualquier otro caso debe mantener la
validación normal y nunca activar un resultado obsoleto o `INVALID`.

#### Scenario: Activación inmediata de un preview válido

- **WHEN** se activa un preview completado y todas sus entradas siguen
  coincidiendo
- **THEN** se persiste ese mismo plan sin ejecutar una segunda resolución

#### Scenario: Entrada modificada después del preview

- **WHEN** cambia la telemetría, previsión, configuración o las consignas desde
  que terminó el preview
- **THEN** el token deja de coincidir y el resultado anterior no se activa

### Requirement: Límite de tiempo configurable del solver

La configuración de planificación debe exponer y persistir
`solver_time_limit_seconds` como entero estrictamente positivo, con valor
predeterminado de 120 segundos. La preview y la planificación automática deben
usar el valor vigente como presupuesto total compartido del solver.

#### Scenario: Configuración válida del límite del solver

- **WHEN** se guarda un límite positivo y entero
- **THEN** se persiste y se aplica a las previews y a la planificación automática

#### Scenario: Configuración inválida del límite del solver

- **WHEN** se intenta guardar cero, un valor negativo o un valor no entero
- **THEN** la API rechaza el cambio y conserva el límite vigente

### Requirement: Ventana y horizonte operativo

La planificación automática y sus vistas previas deben comenzar en el primer
límite de slot que no haya quedado atrás: el límite exacto se conserva y un
instante intermedio se redondea hacia arriba, descartando segundos y
microsegundos. "No haber quedado atrás" se decide en tiempo real, no sobre el
reloj de pared. Deben cubrir exactamente el horizonte configurado, mientras
que la ventana visible inicial comparte ese comienzo y usa su propia duración.
Si falta cobertura AEMET horaria utilizable en cualquier parte del horizonte,
el resultado es explícitamente no planificable y no contiene un plan parcial.

La ventana y el horizonte se cuentan en horas de reloj de pared y sus límites
caen en múltiplos de la duración de slot. Cada slot dura exactamente esa
duración de tiempo real y los límites son estrictamente crecientes, así que el
número de slots del horizonte no es fijo: los dos días del año en que cambia la
hora, un horizonte de 24 horas cubre 25 o 23 horas reales.

#### Scenario: Horizonte que cruza un cambio de hora

- **WHEN** un horizonte de 24 horas con slots de 30 minutos cruza el retroceso
  de octubre o el adelanto de marzo
- **THEN** publica 50 o 46 slots respectivamente, todos de 30 minutos reales,
  contiguos y sin solapes, y ninguna hora del día queda sin planificar

#### Scenario: Previsión de la hora que se repite

- **WHEN** una hora de pared ocurre dos veces por el retroceso de octubre
- **THEN** las dos pasadas usan el valor horario de previsión de esa hora de
  pared y el horizonte sigue considerándose cubierto

#### Scenario: Cobertura meteorológica incompleta

- **WHEN** la previsión no cubre de forma continua el horizonte configurado
- **THEN** la planificación devuelve `INVALID`, explica la falta de cobertura
  y no publica intervalos parciales

#### Scenario: Ventana visible y horizonte completo desde el siguiente slot

- **WHEN** el slot es de 15 minutos, el recálculo ocurre a las 12:10 y la
  ventana y el horizonte son de 12 y 24 horas
- **THEN** ambos comienzan a las 12:15, la ventana termina a las 00:15 y el
  horizonte termina a las 12:15 del día siguiente

### Requirement: Fuente canónica del límite total

La potencia total contratada debe tener una única fuente editable:
`contracted_power_w` en la configuración de Planificación. La planificación
automática, el indicador de Estado y cualquier plan de respaldo deben usar ese
mismo valor; el campo de instalación heredado solo se conserva por
compatibilidad y no puede sobrescribirlo.

#### Scenario: Potencias heredada y canónica diferentes

- **WHEN** `contracted_power_w` difiere de `max_total_power_w`
- **THEN** Estado y la respuesta de planificación muestran y aplican
  `contracted_power_w`

### Requirement: Vista previa durable y cancelable

Cada vista previa se ejecuta como un trabajo persistente con pasos ordenados y
estado consultable. El operador puede recuperar el trabajo tras recargar y
solicitar su cancelación; un trabajo cancelado o interrumpido no puede activar
un plan.

#### Scenario: Cancelación durante una vista previa

- **WHEN** el operador solicita cancelar un trabajo en curso
- **THEN** el trabajo muestra `cancelling`, termina de forma segura en un límite
  de fase y queda `cancelled` sin resultado activable

### Requirement: Consulta compacta de la vista previa

La vista previa debe representar únicamente su ventana visible con una
visualización compacta de series por acumulador. Cada acumulador debe conservar
una tabla accesible por intervalo, etiquetado como inicio-fin, con potencia,
energía almacenada en ambos bordes, temperatura interior en ambos bordes,
objetivo, calor entregado, intercambio térmico, déficit de ambos bordes y SOC. Si
existen déficits o violaciones, la vista
previa debe ofrecer un diálogo accesible con el acumulador, requisito,
momento, valores objetivo/proyectado/déficit, causa explicada y acción
recomendada cuando exista; `deficits` tiene prioridad sobre `violations` como
fuente de problemas.

#### Scenario: Preview degradada con problemas

- **WHEN** una vista previa `DEGRADED` contiene uno o más déficits o violaciones
- **THEN** se muestra el botón de detalle y el diálogo enumera todos los
  problemas con sus valores y explicación, sin limitarse al contador

#### Scenario: Preview sin problemas

- **WHEN** una vista previa `FEASIBLE` no contiene déficits ni violaciones
- **THEN** no se muestra el botón de problemas

### Requirement: Separación de contextos en la vista de planificación

La vista de Planificación debe ofrecer tres pestañas accesibles, en este orden:
Planificación activa, Nueva planificación y Previsión meteorológica. Debe abrir
en Planificación activa; esta pestaña solo muestra el plan aceptado y sus
gráficos, Nueva planificación concentra consignas térmicas y preview, y Previsión
meteorológica concentra el resumen y gráfico meteorológico. Cambiar de pestaña
no debe perder la edición ni el trabajo de preview en curso.

#### Scenario: Llegada a la vista de planificación

- **WHEN** el operador entra en Planificación
- **THEN** se selecciona Planificación activa y no se mezcla su contenido con
  consignas, preview o detalle meteorológico

#### Scenario: Consulta o edición separada

- **WHEN** el operador selecciona Nueva planificación o Previsión meteorológica
- **THEN** ve únicamente el ámbito correspondiente y puede volver al plan
  activo conservando el estado de edición y de preview

### Requirement: Detalle tabular de la planificación activa

La pestaña Planificación activa debe reservar sus tarjetas para las gráficas y
ofrecer el detalle de cada una mediante su botón “Ver detalle”. Cada diálogo de
detalle de gráfica debe mostrar únicamente una tabla accesible, con el intervalo
como cabecera de fila y una columna por acumulador cuando aplique. El diálogo
debe aprovechar el ancho disponible y limitar el scroll al contenedor de la tabla
cuando el número de columnas lo requiera. Las gráficas de potencia representan
ocupación discreta por slot; las térmicas usan los bordes temporales reales y un
rango vertical derivado de sus datos; la carga almacenada se representa en un
eje común de 0–100% y su tabla conserva los kWh de inicio y fin.

#### Scenario: Consulta del detalle de una gráfica activa

- **WHEN** el operador pulsa “Ver detalle” en una de las cuatro gráficas de
  Planificación activa
- **THEN** se abre un diálogo amplio con la tabla correspondiente, sin volver a
  mostrar la gráfica ni añadir una tabla inline a la tarjeta

#### Scenario: Datos ausentes en el detalle tabular

- **WHEN** un intervalo no tiene un valor de temperatura utilizable
- **THEN** la celda correspondiente muestra “sin dato” y conserva el resto de
  columnas e intervalos consultables

### Requirement: Feedback de las acciones del editor de planificación

El editor de Nueva planificación debe hacer visible el resultado de sus
acciones. Descartar debe restaurar inmediatamente las consignas guardadas y
retirar la preview local; Guardar y activar debe indicar el estado en curso, el
éxito o el error sin confundir una preview persistida con el resultado de la
activación.

#### Scenario: Descartar cambios locales

- **WHEN** el operador modifica una consigna y pulsa “Descartar”
- **THEN** los controles recuperan los valores guardados, se limpia la preview
  local y se muestra una confirmación sin una nueva petición de lectura

#### Scenario: Activación correcta o fallida

- **WHEN** el operador pulsa “Guardar y activar” con una preview válida
- **THEN** el botón se bloquea mientras espera y después muestra un éxito
  explícito si la API confirma la activación, o una alerta accionable si la API
  la rechaza, manteniendo la preview para poder corregirla y reintentar

### Requirement: Protección de salidas GPIO

El controlador no debe arrancar salidas GPIO cuando la simulación de
acumuladores está activa. MQTT puede estar deshabilitado porque sus valores
fijos son válidos para instalaciones de prueba y para la prueba de relés.

#### Scenario: Simulación de acumuladores con GPIO

- **WHEN** se solicita arrancar el controlador GPIO con
  `mqtt_simulation_enabled` activo
- **THEN** el arranque falla de forma crítica antes de accionar una salida

#### Scenario: MQTT deshabilitado con GPIO

- **WHEN** se solicita arrancar el controlador GPIO con MQTT deshabilitado y la
  simulación de acumuladores inactiva
- **THEN** el arranque continúa y la prueba de relés puede utilizar las salidas
  físicas
