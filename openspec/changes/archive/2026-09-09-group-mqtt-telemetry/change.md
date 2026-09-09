# Agrupar telemetría MQTT y descubrimiento de Home Assistant

Status: approved

## Goal

Reducir el número de topics MQTT por acumulador sin perder la separación entre
estado publicado, telemetría recibida y mandos. El contrato nuevo debe permitir
que Home Assistant descubra cada dispositivo con menos mensajes y conservar la
semántica actual de disponibilidad.

## Requirements

- R1: Cada acumulador debe tener un único `telemetry_topic` configurable para
  recibir temperatura interior, SOC y, opcionalmente, posición de compuerta.
- R2: Un mensaje de telemetría debe ser un objeto JSON con las claves
  `indoor_temperature_c`, `stored_soc_percent` y
  `damper_position_percent`; cada clave presente se valida y persiste de forma
  independiente, y una clave ausente no borra su último valor válido.
- R3: El servicio debe suscribirse al `telemetry_topic` y dejar de suscribirse
  a topics separados de temperatura, SOC o compuerta. Los mandos y estados
  publicados mantienen sus topics actuales.
- R4: La simulación debe publicar un único JSON de telemetría por acumulador
  habilitado en `<simulation_prefix>/<id>/telemetry`, salvo que exista un
  `telemetry_topic` configurado, respetando el intervalo de simulación actual.
- R5: El descubrimiento MQTT debe agrupar en un mensaje de dispositivo las
  entidades que compartan política de disponibilidad; las entidades que
  dependan además de `state_available` pueden conservar configuración individual.
- R6: La migración de configuración sustituye los campos de topics separados
  por `telemetry_topic` sin inventar una combinación cuando los topics antiguos
  eran distintos; esa configuración deberá quedar pendiente de completar.

## Acceptance

- A1: Para un acumulador configurado, existe una sola suscripción de telemetría
  y un JSON con temperatura y SOC actualiza ambos valores correctamente.
- A2: Un JSON que solo contiene una de las claves actualiza solo ese valor; un
  valor inválido invalida únicamente ese campo.
- A3: La simulación emite una publicación por acumulador y no dos publicaciones
  independientes de temperatura y SOC.
- A4: Los topics y payloads de `state`, `set/enabled`, `availability` y
  `state_available` siguen funcionando como antes.
- A5: Home Assistant crea una instalación y un dispositivo por acumulador, sin
  duplicar entidades, y las entidades dependientes del controlador siguen
  quedando no disponibles cuando `state_available` es `offline`.
- A6: Las pruebas del contrato MQTT, la migración y el descubrimiento pasan, y
  `make check` termina correctamente.
