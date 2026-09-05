# Optimización del solver de planificación

Status: approved

## Goal

Reducir drásticamente el tiempo de cálculo del planificador manteniendo la
misma semántica de factibilidad, prioridades, desempates y estados públicos.
Además, evitar que la activación vuelva a resolver un preview que ya terminó
con los mismos datos.

## Requirements

- R1: El modelo MILP incorporará, en el horizonte estándar de hasta 24 horas, cotas acumuladas de energía válidas para cada heater y frontera temporal, y eliminará restricciones globales redundantes sin cambiar su conjunto de soluciones factibles ni su orden lexicográfico; el horizonte extendido conservará la formulación dispersa actual.
- R2: El solver registrará, como mínimo en nivel `DEBUG`, duración, estado y tamaño del modelo para cada fase, además del tiempo total consumido y el presupuesto configurado.
- R3: La activación reutilizará un preview persistido completado cuando coincidan instalación, revisiones de configuración y constraints, payload de constraints y token de entrada vigente; en ese caso no invocará al solver.
- R4: Un preview ausente, incompleto o no coincidente seguirá el flujo actual de validación y cálculo, y ningún plan `INVALID` podrá activarse.
- R5: Las pruebas verificarán equivalencia funcional del modelo optimizado, reutilización segura del preview y ausencia de regresiones en los estados `FEASIBLE`, `DEGRADED` e `INVALID`.

## Acceptance

- A1: Los escenarios deterministas existentes conservan sus estados, puntuaciones, restricciones de potencia, niveles de carga y déficits dentro de la tolerancia numérica actual.
- A2: En el escenario de referencia de 4 heaters, horizonte de 24 horas y slots de 30 minutos, el benchmark documenta al menos un 50 % menos de tiempo de solver o completa todas las fases lexicográficas dentro de un presupuesto de 5 segundos.
- A3: Los logs `DEBUG` permiten identificar la fase que consume el tiempo y contienen variables, restricciones, duración y presupuesto total.
- A4: Activar inmediatamente un preview completado coincidente no realiza una segunda llamada al solver; si cambian sus entradas, la activación lo rechaza o recalcula según el flujo vigente, pero nunca usa un resultado obsoleto.
- A5: `make check` pasa junto con las pruebas backend relevantes.

## Decisions

- D1: Se conservan las variables de energía y se añaden cotas acumuladas exactas; no se usa una relajación ni un gap aproximado.
- D2: La reutilización usa los previews durables existentes, sin caché en memoria ni migración de esquema.
- D3: El backend, horizonte, granularidad y límite temporal por defecto quedan sin cambios.

## Outcome

El benchmark de referencia pasó de aproximadamente 5,06 s a 1,10 s de media
(≈78 % menos) y completó las fases lexicográficas en 24 horas; el horizonte
de 48 horas conserva el comportamiento base. `make check`: 721 pruebas pasadas,
9 omitidas.
