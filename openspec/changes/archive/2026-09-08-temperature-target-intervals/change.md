# Intervalos de consignas térmicas

Status: approved

## Goal

Convertir las consignas semanales de temperatura en intervalos explícitos y
agilizar su edición mediante duplicación. La planificación solo aplicará un
objetivo dentro de un intervalo válido y rechazará configuraciones ambiguas.

## Requirements

- R1: Cada consigna tendrá acumulador, temperatura, hora de inicio, hora de fin,
  días de la semana y estado activo.
- R2: El intervalo será inicio incluido y fin excluido; podrá cruzar medianoche
  y continuará en el día natural siguiente.
- R3: Fuera de cualquier intervalo activo no se aplicará objetivo térmico ni se
  generará déficit de confort.
- R4: El sistema rechazará con un mensaje claro cualquier solape entre
  intervalos del mismo acumulador, incluidos los solapes producidos al cruzar
  medianoche.
- R5: La API, persistencia, planificación, preview y panel usarán el nuevo
  inicio/fin; las consignas antiguas persistidas se eliminarán en la migración
  sin conversión.
- R6: Cada fila editable tendrá un botón «Duplicar» que cree una copia exacta
  en el borrador para modificarla antes de guardar; una copia sin cambios será
  rechazada como solape.

## Acceptance

- A1: La configuración muestra y guarda inicio y fin de cada consigna, y una
  consigna nocturna se aplica correctamente hasta su fin del día siguiente.
- A2: Un acumulador con un hueco entre intervalos no tiene objetivo durante el
  hueco y la planificación no exige confort en él.
- A3: Dos intervalos solapados, también por medianoche, producen un error
  identificable sin guardar cambios parciales.
- A4: Duplicar una fila conserva todos sus campos y permite editar la copia de
  forma independiente.
- A5: La migración elimina las filas antiguas y una instalación sin consignas
  queda explícitamente no planificable hasta configurarlas.
- A6: Tests backend y frontend cubren modelo, solapes, medianoche, migración,
  API y duplicación; `make check` pasa.

## Decisions

- D1: Los días seleccionados identifican el día de inicio del intervalo; un
  intervalo que cruza medianoche ocupa también el día natural siguiente.
- D2: Los nuevos acumuladores conservan el valor inicial existente como
  intervalo de 21 °C, todos los días, de 00:00 a 24:00.
