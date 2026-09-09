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

### Requirement: Telemetría física fija sin broker

Mientras la integración está deshabilitada, el controlador usa temperatura
interior y SOC almacenado fijos como telemetría válida para todos los
acumuladores. La consigna procede siempre de la programación semanal; no se
publican ni consumen valores MQTT de temperatura objetivo o temperatura del
acumulador. Al habilitar MQTT solo son válidas las lecturas interior y SOC
recibidas por MQTT.

#### Scenario: Planificación sin mensajes MQTT

- **WHEN** MQTT está deshabilitado y se recalcula la planificación
- **THEN** cada acumulador recibe temperatura interior y SOC fijos, y el
  objetivo se obtiene de su programación semanal

#### Scenario: Planificación con MQTT habilitado

- **WHEN** MQTT está habilitado y se recalcula la planificación
- **THEN** el controlador usa únicamente la temperatura interior y el SOC MQTT
  persistidos, y no aplica los valores fijos

### Requirement: Telemetría agrupada por acumulador

Cada acumulador puede declarar un único `telemetry_topic`. Los mensajes que
llegan a ese topic son objetos JSON con claves numéricas opcionales
`indoor_temperature_c`, `stored_soc_percent` y `damper_position_percent`.
Cada clave presente se valida y persiste de forma independiente; una clave
ausente conserva el valor y la marca temporal válidos anteriores. La
telemetría recibida no se retiene al publicarla en la simulación.

#### Scenario: Mensaje agrupado válido

- **WHEN** llega un objeto JSON con temperatura y SOC válidos al topic del
  acumulador
- **THEN** ambos valores se guardan con la hora de recepción y el servicio
  mantiene una sola suscripción para ese acumulador

#### Scenario: Actualización parcial o inválida

- **WHEN** llega un objeto con una sola clave válida, o una clave presente no
  contiene un número válido dentro de sus límites
- **THEN** solo se actualiza o invalida esa clave y las demás conservan su
  último valor válido

#### Scenario: Simulación agrupada

- **WHEN** la simulación MQTT está activa para un acumulador habilitado sin
  topic configurado
- **THEN** publica un único objeto JSON en
  `<simulation_prefix>/<id>/telemetry` en cada intervalo configurado

### Requirement: Descubrimiento de dispositivos agrupado

El descubrimiento MQTT de Home Assistant debe publicar un mensaje de dispositivo
por instalación y por acumulador. Las entidades con la misma política de
disponibilidad se declaran dentro de ese mensaje; las entidades que además
dependen de `state_available` pueden conservar una configuración individual.
Los `unique_id`, topics de estado y topics de mando existentes permanecen
estables.

#### Scenario: Estado del controlador no disponible

- **WHEN** `state_available` publica `offline`
- **THEN** las entidades que dependen del estado del controlador aparecen no
  disponibles, mientras las entidades del grupo base conservan la disponibilidad
  del proceso MQTT
