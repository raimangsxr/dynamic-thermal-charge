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

### Requirement: Horizonte operativo completo

La planificación automática y sus vistas previas deben cubrir exactamente las
24 horas continuas desde el siguiente límite de intervalo configurado. Si falta
cobertura AEMET horaria utilizable en cualquier parte de esa ventana, el
resultado es explícitamente no planificable y no contiene un plan parcial.

#### Scenario: Cobertura meteorológica incompleta

- **WHEN** la previsión no cubre de forma continua las próximas 24 horas
- **THEN** la planificación devuelve `INVALID`, explica la falta de cobertura
  y no publica intervalos parciales

### Requirement: Vista previa durable y cancelable

Cada vista previa se ejecuta como un trabajo persistente con pasos ordenados y
estado consultable. El operador puede recuperar el trabajo tras recargar y
solicitar su cancelación; un trabajo cancelado o interrumpido no puede activar
un plan.

#### Scenario: Cancelación durante una vista previa

- **WHEN** el operador solicita cancelar un trabajo en curso
- **THEN** el trabajo muestra `cancelling`, termina de forma segura en un límite
  de fase y queda `cancelled` sin resultado activable

### Requirement: Protección de salidas GPIO

El controlador no debe arrancar salidas GPIO cuando MQTT está deshabilitado o
la simulación de acumuladores está activa.

#### Scenario: Telemetría no real con GPIO

- **WHEN** se solicita arrancar el controlador GPIO con telemetría fija o
  simulada
- **THEN** el arranque falla de forma crítica antes de accionar una salida
