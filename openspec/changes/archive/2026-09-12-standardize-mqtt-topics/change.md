# Estandarizar topics MQTT y reinicializar clientes al guardar

Status: approved

## Goal

Eliminar la configuración repetitiva de topics por acumulador y garantizar que
los cambios de conexión MQTT guardados se apliquen automáticamente sin dejar
clientes usando credenciales antiguas.

## Requirements

- R1: Resolver para cada acumulador los topics estándar
  `telemetria/acumuladores/<id>/telemetry`, `/discharge` y `/setpoint`, usando el
  identificador MQTT normalizado y sin añadir una nueva opción de configuración.
- R2: Usar el topic estándar cuando el topic persistido correspondiente esté
  vacío; los topics explícitos existentes siguen funcionando como overrides de
  compatibilidad.
- R3: La telemetría agrupada y los mandos de descarga deben suscribirse o
  publicarse en el topic efectivo del acumulador, y las respuestas de
  configuración/planificación deben mostrar ese topic efectivo para que el
  operador pueda comprobarlo sin editarlo.
- R4: Tras guardar cambios en `mqtt.enabled`, host, puerto, TLS, prefijos,
  cadencia o credenciales MQTT, el supervisor debe detener el cliente anterior
  y crear automáticamente uno nuevo con la configuración vigente, incluyendo
  el cliente de simulación si está activo.
- R5: Un cambio de otra sección no debe reinicializar los clientes MQTT, y una
  reinicialización no debe crear clientes, bucles ni suscripciones duplicados.

## Acceptance

- A1: Con un acumulador `salon` sin topics persistidos, el proceso usa
  `telemetria/acumuladores/salon/telemetry` para aceptar el JSON de telemetría y
  muestra temperatura y SOC en Estado tras el siguiente mensaje.
- A2: Con `salon` sin topics de mando persistidos, el proceso publica sus
  mandos en `telemetria/acumuladores/salon/discharge` y
  `telemetria/acumuladores/salon/setpoint`.
- A3: Un topic explícito antiguo continúa siendo el topic efectivo de ese
  acumulador y no se publica ni suscribe además el estándar.
- A4: Cambiar usuario o contraseña mientras MQTT está activo provoca una
  desconexión y una nueva conexión que usa los valores nuevos sin reiniciar
  manualmente el contenedor; el mismo comportamiento se cumple para host,
  puerto, TLS y prefijos.
- A5: El cambio de contraseña no deja el cliente anterior ni suscripciones
  duplicadas, y los secretos no aparecen en logs ni respuestas públicas.
- A6: Las pruebas cubren resolución de topics, compatibilidad de overrides,
  recepción/publicación y reinicialización de los supervisores.

## Outcome

Los topics estándar se resuelven de forma compartida, los overrides existentes
siguen siendo efectivos y ambos supervisores recrean el cliente MQTT cuando
cambian sus parámetros o credenciales persistidos.
