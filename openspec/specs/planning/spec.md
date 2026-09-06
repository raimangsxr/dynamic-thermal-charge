## Purpose

Garantizar que la planificación automática solo publica decisiones reproducibles
y ejecutables a partir de previsión y telemetría aptas.

## Requirements

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
token de entrada vigente, las revisiones de configuración y constraints y el
payload de constraints coinciden. En cualquier otro caso debe mantener la
validación normal y nunca activar un resultado obsoleto o `INVALID`.

#### Scenario: Activación inmediata de un preview válido

- **WHEN** se activa un preview completado y todas sus entradas siguen
  coincidiendo
- **THEN** se persiste ese mismo plan sin ejecutar una segunda resolución

#### Scenario: Entrada modificada después del preview

- **WHEN** cambia la telemetría, previsión, configuración o constraints desde
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
microsegundos. Deben cubrir exactamente el horizonte configurado, mientras
que la ventana visible inicial comparte ese comienzo y usa su propia duración.
Si falta cobertura AEMET horaria utilizable en cualquier parte del horizonte,
el resultado es explícitamente no planificable y no contiene un plan parcial.

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
una tabla accesible por intervalo con potencia, energía entregada, porcentaje
de capacidad utilizado y SOC. Si existen déficits o violaciones, la vista
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
gráficos, Nueva planificación concentra constraints y preview, y Previsión
meteorológica concentra el resumen y gráfico meteorológico. Cambiar de pestaña
no debe perder la edición ni el trabajo de preview en curso.

#### Scenario: Llegada a la vista de planificación

- **WHEN** el operador entra en Planificación
- **THEN** se selecciona Planificación activa y no se mezcla su contenido con
  constraints, preview o detalle meteorológico

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
cuando el número de columnas lo requiera.

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
acciones. Descartar debe restaurar inmediatamente las constraints guardadas y
retirar la preview local; Guardar y activar debe indicar el estado en curso, el
éxito o el error sin confundir una preview persistida con el resultado de la
activación.

#### Scenario: Descartar cambios locales

- **WHEN** el operador modifica una constraint y pulsa “Descartar”
- **THEN** los controles recuperan los valores guardados, se limpia la preview
  local y se muestra una confirmación sin una nueva petición de lectura

#### Scenario: Activación correcta o fallida

- **WHEN** el operador pulsa “Guardar y activar” con una preview válida
- **THEN** el botón se bloquea mientras espera y después muestra un éxito
  explícito si la API confirma la activación, o una alerta accionable si la API
  la rechaza, manteniendo la preview para poder corregirla y reintentar

### Requirement: Protección de salidas GPIO

El controlador no debe arrancar salidas GPIO cuando MQTT está deshabilitado o
la simulación de acumuladores está activa.

#### Scenario: Telemetría no real con GPIO

- **WHEN** se solicita arrancar el controlador GPIO con telemetría fija o
  simulada
- **THEN** el arranque falla de forma crítica antes de accionar una salida
