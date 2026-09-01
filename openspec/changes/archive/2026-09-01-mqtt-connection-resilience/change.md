# Evitar publicaciones MQTT antes de conectar

Status: approved

## Goal

Evitar que una carrera entre el arranque de la conexión asíncrona y el primer ciclo de publicación termine el proceso MQTT cuando el broker aún no ha aceptado la conexión.

## Requirements

- R1: El servicio MQTT solo debe publicar estado, disponibilidad o descubrimiento después de recibir una conexión aceptada.
- R2: Mientras la conexión no esté aceptada o se haya perdido, el proceso debe continuar ejecutándose y dejar que el transporte gestione la reconexión automática.
- R3: Tras una reconexión aceptada, el servicio debe conservar el comportamiento existente de republicar disponibilidad, descubrimiento, estado y suscripciones.

## Acceptance

- A1: Un ciclo ejecutado antes de cualquier conexión aceptada no llama a `publisher.refresh()` ni termina con `MqttPublishError`.
- A2: Una desconexión evita publicaciones periódicas hasta que llegue una nueva conexión aceptada.
- A3: Las pruebas existentes de arranque, reconexión y suscripciones siguen pasando, junto con una prueba que cubra la carrera de conexión inicial.

## Outcome

El servicio mantiene el proceso activo durante la conexión inicial y las desconexiones, y reanuda las publicaciones al aceptar una conexión.
