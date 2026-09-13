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

#### Scenario: Cambia una configuración MQTT activa

- **WHEN** se guarda un cambio en host, puerto, TLS, prefijos, cadencia o en las credenciales MQTT mientras la integración está activa
- **THEN** el proceso detiene el cliente anterior y crea un único cliente nuevo con la configuración vigente en el siguiente ciclo, sin duplicar bucles ni suscripciones

#### Scenario: Cambia una sección no MQTT

- **WHEN** se guarda una sección que no modifica la configuración MQTT ni sus credenciales
- **THEN** el cliente MQTT activo continúa sin reinicializarse

### Requirement: Esquema MQTT único y sin overrides

Todos los topics propios usan `mqtt.prefix`, cuyo valor predeterminado es
`telemetria`. La única excepción es `mqtt.discovery_prefix`, que se usa solo
para los topics de descubrimiento de Home Assistant. Cada acumulador deriva
sus topics de telemetría, descarga y consigna de ese prefijo y de su
identificador normalizado. La aplicación no acepta ni lee
`telemetry_topic`, `damper_topic` o `setpoint_topic` como overrides y no
publica ni se suscribe a los namespaces `dtc/...`.

#### Scenario: Prefijo MQTT personalizado

- **WHEN** `mqtt.prefix` vale `casa`
- **THEN** los topics de instalación y de cada acumulador empiezan por
  `casa/`, mientras los topics de descubrimiento siguen empezando por
  `mqtt.discovery_prefix`

#### Scenario: Topic legacy recibido

- **WHEN** llega un mensaje a un topic `dtc/...` o a un topic configurado por
  un override retirado
- **THEN** el controlador lo ignora y no publica una copia en el esquema nuevo

### Requirement: Telemetría física solo con evidencia fresca

Mientras MQTT está deshabilitado o falta una muestra MQTT fresca de un
acumulador, ese acumulador no tiene telemetría válida para planificar. No se
usan temperaturas interiores ni SOC fijos o fabricados. La consigna procede
siempre de la programación semanal.

#### Scenario: Planificación sin telemetría MQTT válida

- **WHEN** MQTT está deshabilitado o la temperatura interior o el SOC han
  caducado
- **THEN** la planificación devuelve `INVALID`, no incluye valores sintéticos
  y las salidas permanecen seguras

### Requirement: Telemetría agrupada por acumulador

Cada acumulador tiene tres topics estándar bajo
`<prefijo>/acumuladores/<id-normalizado>`: `telemetry`, `discharge` y
`setpoint`. El identificador usa el mismo slug seguro que la identidad MQTT.
Los mensajes que llegan al topic estándar de telemetría son
objetos JSON con claves numéricas opcionales
`indoor_temperature_c`, `stored_soc_percent` y `damper_position_percent`.
Cada clave presente se valida y persiste de forma independiente; una clave
ausente conserva el valor y la marca temporal válidos anteriores. La
telemetría recibida no se retiene.

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
