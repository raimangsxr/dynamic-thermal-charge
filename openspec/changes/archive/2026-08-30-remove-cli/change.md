# Retirar el CLI de la aplicación

Status: approved

## Goal

Eliminar el CLI Python de Dynamic Thermal Charge y sus restos de despliegue y pruebas, manteniendo el arranque automático de la instalación y los servicios API, controlador y MQTT.

## Requirements

- R1: El backend no expone ni contiene un CLI de aplicación basado en parser de argumentos, módulo `__main__` o comandos administrativos interactivos.
- R2: API, controlador y MQTT se pueden iniciar mediante entrypoints programáticos explícitos, sin cambiar sus contratos funcionales ni añadir un binario alternativo.
- R3: El despliegue deja de invocar comandos del CLI y conserva la inicialización idempotente de bootstrap, esquema, configuración funcional y token administrador usando el entorno existente.
- R4: Se eliminan los tests, documentación y referencias de runtime que solo existen para el CLI; se conservan las pruebas de dominio, persistencia, API y servicios.
- R5: Angular CLI queda fuera de este cambio como herramienta de build del frontend, no como CLI de la aplicación.

## Acceptance

- A1: `backend/src/dynamic_thermal_charge/cli.py`, `backend/src/dynamic_thermal_charge/__main__.py` y las pruebas exclusivas del CLI ya no existen.
- A2: `deploy/compose.yaml`, `backend/entrypoint.sh`, `Makefile` y Dockerfiles no invocan comandos del CLI de la aplicación.
- A3: Un despliegue nuevo sigue inicializando la persistencia una sola vez de forma segura y arranca API, controlador y MQTT sin argumentos de CLI.
- A4: `make check` pasa completo y las pruebas restantes cubren el comportamiento conservado.

## Decisions

- D1: La inicialización y los procesos se exponen como funciones/módulos internos de arranque; no se añade un nuevo parser, console script ni binario.
- D2: Se mantiene el contrato operativo de `DTC_API_TOKEN` y de los volúmenes persistentes; no se introduce una migración de datos.
- D3: La dependencia `@angular/cli` y los comandos `ng` se mantienen porque son tooling de compilación, no superficie CLI de la aplicación.
