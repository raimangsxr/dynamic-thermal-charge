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

La capacidad de emisión decae con el estado de carga. La potencia máxima de
emisión es `capacidad kWh / horas de descarga nominal` y la residual es un
porcentaje configurado de esa máxima; el calor entregado en un intervalo no
puede superar
`(P_residual + (P_emisión − P_residual) × SOC) × duración real del intervalo`,
con el SOC del borde inicial del intervalo, ni la energía disponible después de
sumar la carga de ese intervalo. El límite se aplica también cuando carga y
descarga coinciden, y la emisión residual es una capacidad y no una emisión
forzada: un acumulador vacío entrega cero.

El calor entregado es cero en los intervalos sin consigna activa a partir de
los cuales ninguna consigna del horizonte queda por delante. En los intervalos
anteriores a una consigna la emisión sigue permitida, de modo que el plan puede
precalentar hacia su borde inicial.

Cuando una consigna está activa en un slot, la temperatura objetivo es una
invariante en sus dos bordes: se evalúan tanto `T_inside` al inicio como
`T_next` al final. El optimizador puede usar slots anteriores sin consigna para
precalentar, pero un déficit en cualquiera de esos bordes conserva la
observación y deja el plan como `DEGRADED` salvo que pueda demostrar una
convergencia posterior continuada en todos los bordes con consigna activa.

#### Scenario: Exterior más cálido que el interior

- **WHEN** la temperatura exterior supera la interior durante un intervalo
- **THEN** el intercambio térmico es negativo, aumenta la temperatura
  proyectada y se conserva el balance energético firmado

#### Scenario: Descarga limitada por la capacidad de emisión

- **WHEN** una consigna requiere más calor que el que el acumulador puede
  emitir con su estado de carga durante un intervalo
- **THEN** el modelo y el optimizador entregan como máximo esa capacidad por la
  duración real del intervalo, conservan la energía almacenada no negativa y
  registran el déficit térmico como `DEGRADED`

#### Scenario: Acumulador poco cargado ante una consigna

- **WHEN** el estado de carga es bajo y la consigna exige subir o mantener la
  temperatura
- **THEN** la capacidad de emisión proyectada decae con ese estado de carga, el
  déficit resultante se conserva y el plan no proyecta una emisión a la potencia
  de un acumulador lleno

#### Scenario: Intervalo sin ninguna consigna por delante

- **WHEN** un intervalo no tiene consigna activa y ninguna consigna del
  horizonte queda por delante de él
- **THEN** el calor entregado en ese intervalo es cero

### Requirement: Consignas semanales y fuente del objetivo

Cada acumulador habilitado debe tener una o más consignas semanales de
temperatura, intervalo horario local, días de la semana y estado activo. El
inicio del intervalo se incluye y el fin se excluye; un intervalo cuyo fin es
anterior al inicio continúa en el día natural siguiente. La planificación usa
la consigna solo mientras el instante pertenece a un intervalo activo, no
mantiene una consigna durante los huecos y nunca usa telemetría de temperatura
del acumulador ni deriva una temperatura desde el SOC. Los intervalos de un
mismo acumulador no pueden solaparse, incluso al cruzar medianoche.

La interfaz inline de Nueva planificación presenta las reglas en una lista
vertical con una única vista de detalle editable para la consigna seleccionada.
La lista resume acumulador, temperatura, días, horario y estado; conserva los
índices de día lunes=0 a domingo=6 y representa `end_time: "24:00"` como
medianoche sin alterar el payload. El inicio se muestra como incluido y el fin
como excluido; los cambios no inician una vista previa hasta que el operador la
solicita.

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

#### Scenario: Orden lexicográfico de la optimización

- **WHEN** existen varias decisiones que cubren las mismas consignas
- **THEN** se conserva primero la seguridad y el confort por prioridad, después
  se minimiza la energía eléctrica cargada, el excedente terminal y el calor
  fuera de consigna, y finalmente se eligen los slots más tardíos con un
  desempate determinista

#### Scenario: Evolución exterior suficiente

- **WHEN** la previsión exterior y el modelo térmico mantienen todos los bordes
  de una consigna dentro de sus límites sin cargar
- **THEN** no se asigna carga eléctrica anticipada ni residual

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

### Requirement: Estados canónicos y convergencia continuada

La planificación pública y persistida usa `VALID`, `CONVERGING`, `DEGRADED` e
`INVALID`. Solo `VALID` y `CONVERGING` son activables. `CONVERGING` exige un
déficit inicial y un borde posterior con consigna activa desde el que todos los
bordes activos siguientes cumplen hasta el final del horizonte; el final de una
ventana o un hueco sin consigna no prueban convergencia. La respuesta conserva
la hora de convergencia por acumulador, la hora global y el final del horizonte
garantizado, además de las observaciones originales que explican el resultado.
Los planes históricos con `FEASIBLE` se leen y exponen como `VALID`.

#### Scenario: Activación de un plan convergente

- **WHEN** un preview `CONVERGING` tiene evidencia de cumplimiento continuado
- **THEN** se activa desde el siguiente límite de slot que no haya pasado y
  publica la hora de convergencia y el horizonte garantizado

#### Scenario: Candidato degradado durante una replanificación

- **WHEN** un recálculo produce `DEGRADED` mientras existe un plan `VALID` o
  `CONVERGING` con slots vigentes
- **THEN** el candidato no sustituye al plan activo, la degradación queda
  visible y el sistema continúa recalculando

#### Scenario: Histórico con estado anterior

- **WHEN** se consulta un plan persistido con estado `FEASIBLE`
- **THEN** se devuelve como `VALID` sin perder sus slots, explicaciones ni
  auditoría

### Requirement: Replanificación por desviación medida

En cada límite de slot, con control automático y un plan activo, el controlador
debe reproyectar todos sus intervalos restantes desde la temperatura interior y
el SOC medidos, conservando sus decisiones de carga y sin resolver el MILP. Los
déficits se comparan por acumulador y borde temporal contra la serie física
persistida del plan: un déficit nuevo o agravado por encima de la tolerancia
solicita un recálculo inmediato. Si no hay déficits y la energía final
reproyectada supera la prevista por más de la tolerancia de SOC, también debe
recalcularse para evitar carga innecesaria.

Solo puede solicitarse un recálculo por desviación en cada slot. Un acumulador
sin ambas medidas recientes se omite sin impedir que otro acumulador comprobable
dispare el recálculo. El motivo, el acumulador, el borde y los valores comparados
quedan en la auditoría. Un resultado `INVALID` de esta comprobación se guarda
sin sustituir el plan activo; un `INVALID` periódico conserva su tratamiento
seguro habitual.

#### Scenario: Déficit nuevo tras una convergencia inicial

- **WHEN** un plan `CONVERGING` ya preveía un déficit inicial mayor, pero la
  reproyección descubre un déficit nuevo en un borde posterior
- **THEN** la comparación de ese borde solicita un recálculo aunque el máximo
  global del horizonte no haya aumentado

#### Scenario: Excedente tras recargar un plan persistido

- **WHEN** la reproyección cumple todas las consignas y termina por encima de la
  energía final guardada en la serie física del plan
- **THEN** solicita un recálculo si la diferencia supera la tolerancia de SOC,
  incluso después de reiniciar el proceso

### Requirement: Accionamiento de la descarga por MQTT

El plan activo debe accionar la descarga de cada acumulador. Cuando el plan
indica emisión en el intervalo vigente, el sistema publica la activación de la
descarga en el topic de compuerta del acumulador y la temperatura objetivo
vigente en su topic de consigna; cuando deja de indicarla, publica la
desactivación y el sentinel textual `NULL` en el topic de consigna configurado,
sin publicar una consigna numérica. La emisión está indicada mientras una
consigna esté activa y también en un intervalo anterior sin consigna en el que
el plan proyecte calor entregado, caso en el que la consigna publicada es la de
la próxima consigna que motiva esa emisión.

El mando activa o desactiva la descarga; no ordena abrir la compuerta. El
termostato del acumulador la modula contra la consigna publicada, cerrándola al
alcanzar el objetivo y abriéndola cuando la estancia se enfría. Una posición de
compuerta cerrada recibida por telemetría mientras la descarga está activada no
es una discrepancia y no genera alerta.

Los mandos se reafirman en cada ciclo de publicación y no se publican con
retención, de modo que el broker nunca entregue una orden obsoleta. Se publica
la desactivación cuando no hay plan activo, el plan es `INVALID`, el control
automático está desactivado, el acumulador está en modo `OFF`, hay una prueba de
relés en curso o el estado del controlador no está vigente. Un acumulador sin
topic de compuerta configurado no recibe mando y no impide el del resto. El
estado publicado por acumulador debe distinguir la descarga comandada de la
posición de compuerta recibida. Cuando la descarga está desactivada, el topic de
consigna configurado recibe el sentinel textual `NULL` para que el acumulador
pueda limpiar su indicación de temperatura objetivo.

#### Scenario: Consigna activa en el intervalo vigente

- **WHEN** el plan activo tiene una consigna activa para un acumulador en el
  intervalo que contiene el instante actual
- **THEN** se publica la activación de su descarga y su consigna, sin retención

#### Scenario: Fin del intervalo de consigna

- **WHEN** termina el intervalo de consigna y el plan no proyecta calor para ese
  acumulador
- **THEN** se publica la desactivación de su descarga y `NULL` en su topic de
  consigna configurado

#### Scenario: Anticipación antes de una consigna

- **WHEN** el plan proyecta calor entregado en un intervalo sin consigna activa
- **THEN** se publica la activación de la descarga y la consigna de la próxima
  ventana del plan

#### Scenario: Compuerta cerrada con la descarga activada

- **WHEN** la telemetría informa de una compuerta cerrada mientras la descarga
  está activada
- **THEN** el mando se mantiene y no se registra ni se publica discrepancia

#### Scenario: Condición degradada

- **WHEN** no hay plan activo, el plan es `INVALID`, el control automático está
  desactivado, el acumulador está en modo `OFF`, hay una prueba de relés en curso
  o el estado del controlador no está vigente
- **THEN** se publica la desactivación de la descarga y `NULL` en su topic de
  consigna configurado

#### Scenario: Acumulador sin topic de compuerta

- **WHEN** un acumulador no tiene topic de compuerta configurado
- **THEN** no recibe mando alguno, la condición se registra una vez y el resto de
  acumuladores del mismo ciclo reciben el suyo

### Requirement: Auditoría física del plan

Las vistas previas, el plan activo, las explicaciones y el historial deben
conservar por acumulador e intervalo la temperatura interior proyectada y la
energía almacenada en los bordes de inicio y fin, la consigna, el SOC, el calor
entregado, el límite de emisión aplicado, el intercambio térmico y los déficits
de temperatura de ambos bordes cuando existan. La capacidad total en kWh debe estar disponible para expresar el
SOC relativo de cada acumulador.

#### Scenario: Consulta de un intervalo planificado

- **WHEN** el operador abre el detalle de un intervalo
- **THEN** puede distinguir los valores de inicio y fin de energía almacenada,
  carga, calor entregado, límite de emisión aplicado, intercambio térmico,
  interior, objetivo y déficit sin inferir temperatura a partir del SOC

#### Scenario: Balance físico de la vista previa activada

- **WHEN** se activa una vista previa con telemetría y balances físicos
- **THEN** el detalle de la vista previa y la explicación persistida muestran la
  misma serie de inicio, carga, calor, intercambio, fin y déficit, y sus totales
  se reconcilian con los intervalos

### Requirement: Explicación durable de la planificación

Cada cálculo debe conservar la evidencia estructurada que empleó, sin secretos,
y relacionarse con el plan que gobernaba las salidas al comenzar. La explicación
del plan activo o histórico debe derivarse de esa evidencia mediante reglas
deterministas, mostrar el balance físico por intervalo y permitir descargar un
diagnóstico con su comparación, auditoría y transiciones. Nunca debe reconstruir
datos ausentes a partir del estado actual.

#### Scenario: Replanificación frente al plan gobernante

- **WHEN** un nuevo cálculo sucede a un plan que gobernaba las salidas
- **THEN** la explicación compara entradas, carga, estado final y déficits contra
  ese plan, e indica si lo reemplazó o si el candidato no llegó a activarse

#### Scenario: Plan anterior sin evidencia conservada

- **WHEN** el operador consulta un plan creado antes de conservar snapshots
- **THEN** el plan sigue siendo consultable y la evidencia ausente figura como
  no disponible, sin inferirse de la configuración, telemetría o previsión vigente

#### Scenario: Métrica ausente frente a cero físico

- **WHEN** una métrica no fue guardada en un plan histórico o su cálculo físico
  es exactamente cero
- **THEN** la primera se muestra como no disponible y la segunda permanece como
  cero en la explicación y el detalle por intervalo

#### Scenario: Motivo de cada carga

- **WHEN** el planificador asigna energía a un acumulador
- **THEN** la explicación identifica la próxima consigna y su límite, la
  contribución del intercambio exterior y la energía terminal, distinguiendo
  carga necesaria, precalentamiento y residual

#### Scenario: Descarga de diagnóstico

- **WHEN** el operador descarga el diagnóstico de un plan
- **THEN** recibe un documento legible por máquina con la evidencia conservada,
  comparación y eventos relacionados, sin credenciales ni secretos

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

Un plan solo será `VALID` si todas las fases del solver alcanzan el óptimo y
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

- **WHEN** una vista previa `VALID` no contiene déficits ni violaciones
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
