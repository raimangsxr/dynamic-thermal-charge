# Persist active charge plans in the database

Status: approved

## Goal

Eliminar la persistencia runtime del plan activo en `active-plan.json`. El
controlador debe guardar y recuperar su último plan aceptado exclusivamente
desde el almacén de aplicación de la base de datos.

## Requirements

- R1: El runtime no construirá `PlanStore`, no leerá ni escribirá `state_file` y
  no emitirá logs que indiquen persistencia del plan en un fichero.
- R2: El último plan aceptado por el controlador, incluidos sus intervalos,
  asignaciones y minutos no atendidos, se guardará en la base de datos de
  aplicación y se recuperará tras reiniciar el proceso.
- R3: La persistencia del plan será consistente por instalación y conservará la
  política actual: ante una indisponibilidad transitoria de la base de datos se
  mantiene el plan en memoria y se reintenta; un plan inválido o inexistente
  deja todas las salidas apagadas.
- R4: La configuración pública y el modelo dejarán de exponer `state_file`;
  los valores de configuración runtime que sigan siendo necesarios continuarán
  almacenándose en la base de datos.

## Acceptance

- A1: Las pruebas demuestran que el controlador guarda y recupera un plan
  desde una base de datos nueva, sin crear ni necesitar `active-plan.json`.
- A2: Las pruebas cubren la continuidad durante una caída transitoria de la
  base de datos y el estado seguro sin plan recuperable.
- A3: Las pruebas de configuración y API ya no esperan ni aceptan `state_file`.
- A4: `make check` pasa.

## Outcome

El runtime persiste el plan aceptado en las tablas de planes de la base de
datos de aplicación, elimina `state_file` de la configuración pública y arranca
sin plan recuperable cuando la BD no contiene uno.
