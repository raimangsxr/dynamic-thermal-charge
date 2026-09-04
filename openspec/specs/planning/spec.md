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

### Requirement: Protección de salidas GPIO

El controlador no debe arrancar salidas GPIO cuando MQTT está deshabilitado o
la simulación de acumuladores está activa.

#### Scenario: Telemetría no real con GPIO

- **WHEN** se solicita arrancar el controlador GPIO con telemetría fija o
  simulada
- **THEN** el arranque falla de forma crítica antes de accionar una salida
