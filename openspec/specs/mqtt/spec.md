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

### Requirement: Integración desactivable en caliente

La integración MQTT debe permanecer inerte cuando `mqtt.enabled` es falso y
reconciliar su ciclo de vida con los cambios persistidos sin reiniciar los demás
procesos.

#### Scenario: MQTT deshabilitado al arrancar

- **WHEN** el proceso MQTT lee `mqtt.enabled` como falso
- **THEN** no crea el cliente ni inicia conexión, bucle de red, publicaciones o suscripciones

#### Scenario: MQTT cambia de estado

- **WHEN** `mqtt.enabled` cambia entre falso y verdadero, o de verdadero a falso
- **THEN** el proceso inicia o detiene la conexión MQTT en el siguiente ciclo de reconciliación

### Requirement: Telemetría fija sin broker

La configuración MQTT conserva cuatro valores globales fijos y, mientras la
integración está deshabilitada, el controlador los usa como telemetría válida
para todos los acumuladores y como lectura interior disponible. Al habilitar
MQTT solo son válidas las lecturas recibidas por MQTT.

#### Scenario: Planificación sin mensajes MQTT

- **WHEN** MQTT está deshabilitado y se recalcula la planificación
- **THEN** cada acumulador recibe temperatura, temperatura objetivo y carga almacenada fijas, y la temperatura interior fija se usa en el cálculo

#### Scenario: Planificación con MQTT habilitado

- **WHEN** MQTT está habilitado y se recalcula la planificación
- **THEN** el controlador usa únicamente la telemetría MQTT persistida y no aplica los valores fijos
