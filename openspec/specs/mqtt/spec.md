## Purpose

Publicar el estado de la instalación de forma resiliente ante conexiones MQTT asíncronas o interrumpidas.

## Requirements

### Requirement: Publicación condicionada a conexión aceptada

El servicio MQTT no debe publicar estado, disponibilidad, descubrimiento ni suscripciones mientras no haya procesado una conexión aceptada. Debe continuar ejecutándose durante ese intervalo y reanudar las publicaciones cuando se acepte una conexión nueva.

#### Scenario: Broker aún no conectado

- **WHEN** comienza un ciclo periódico antes de recibir una conexión aceptada
- **THEN** el servicio omite la publicación y permanece ejecutándose

#### Scenario: Conexión perdida

- **WHEN** el servicio procesa una desconexión
- **THEN** omite las publicaciones periódicas hasta procesar una reconexión aceptada
