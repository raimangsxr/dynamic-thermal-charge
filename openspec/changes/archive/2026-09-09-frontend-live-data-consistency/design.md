# Design

## Durable approach

El estado operativo usa un read-model compartido basado en `automatic_plan` y
la previsión más reciente; el histórico combina filas automáticas y legacy con
origen y cursor deterministas. La UI comparte catálogos, nombres, instantes y
estado del ciclo meteorológico, manteniendo los detalles técnicos como
información secundaria.

## Constraints retained

- No se activan salidas físicas ni se cambia el contrato de seguridad de relés.
- No se eliminan datos legacy ni se hace una migración destructiva.
- API y persistencia conservan instantes UTC; la presentación usa la zona de la
  instalación.
