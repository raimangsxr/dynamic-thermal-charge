# Dynamic Thermal Charge

Controlador de acumuladores térmicos con API, MQTT, panel web e integración
nativa para Home Assistant.

## Estructura

- `backend/`: código Python, pruebas, empaquetado, imagen y entrypoint.
- `frontend/`: aplicación Angular e imagen nginx.
- `deploy/`: Compose, reconciliador y versión desplegada.
- `openspec/` y `specs/`: diseño y especificaciones del proyecto.

## Desarrollo

El entorno que ejecuta `make setup` y `make check` debe usar Python **3.14.2 o
posterior**, porque la integración nativa se prueba con Home Assistant Core
2026.9.1. El backend de producción mantiene `>=3.12`; esta diferencia solo
afecta a la puerta de calidad y a las pruebas de la integración.

```sh
make setup   # entorno de backend en backend/.venv y dependencias del panel
make test    # pruebas de backend y de frontend
make lint    # ruff sobre el backend
make check   # test + lint + build del panel + validación de los Compose
make dev     # valida la configuración persistida
```

`make check` es la misma puerta que ejecuta CI, así que un test de frontend en
rojo o un hallazgo del linter impiden mezclar. La suite informa del porcentaje
de cobertura total y trata como error cualquier advertencia emitida por el
propio proyecto; las deprecaciones de terceros toleradas están enumeradas una a
una en `backend/pyproject.toml`.

El backend se instala en `backend/.venv`, que es el intérprete que usan `make
test` y `make lint` cuando existe. El panel se compila siempre fuera del
dispositivo.

## Integración con Home Assistant

La integración nativa soporta Home Assistant Core **2026.9.1**. La instalación
manual requiere esa versión de Home Assistant, acceso de red al backend y el
token Bearer configurado en `DTC_API_TOKEN` (el puerto habitual es `8080`). El
backend debe ser accesible desde la red de Home Assistant; la integración no
usa la API del panel web.

Para instalarla:

1. Descarga el árbol de esta versión y copia exactamente
   `custom_components/dynamic_thermal_charge` a
   `/config/custom_components/dynamic_thermal_charge` (o usa el editor de
   archivos de Home Assistant).
2. Reinicia Home Assistant y espera a que termine el arranque.
3. En `Ajustes → Dispositivos y servicios → Añadir integración`, busca
   `Dynamic Thermal Charge`, selecciona `http` para una red local o `https`
   para un endpoint TLS, e introduce host, puerto y token por separado.

En HTTPS se valida siempre la cadena de confianza y el nombre del certificado;
no hay una opción para desactivar esa comprobación. Un certificado autofirmado
o cuyo nombre no coincida se rechaza. Las entradas creadas por versiones
anteriores que no guardaban protocolo se migran automáticamente a HTTP,
conservando su UUID, dispositivos y entidades.

Comprobación básica: abre el dispositivo controlador y confirma que el sensor
`State` tiene uno de `running`, `idle`, `degraded` o `error`; después revisa que
el calendario y el sensor de un acumulador muestren datos. Si no hay conexión o
autenticación, las entidades aparecen como no disponibles y no muestran una
lectura antigua como actual.

Para actualizar, sustituye el directorio por el de la nueva versión, conserva
la entrada de configuración y reinicia Home Assistant. Para desinstalar,
elimina la integración desde `Ajustes → Dispositivos y servicios`, borra
`/config/custom_components/dynamic_thermal_charge` y reinicia; los datos del
backend no se borran.

El backend sigue siendo la autoridad: Home Assistant solo lee snapshots y
envía comandos autenticados con revisión optimista. La integración consulta un
snapshot coherente cada 30 segundos y solicita una actualización inmediata tras
cualquier comando. Si falla la conexión o la autenticación, todas las entidades
quedan no disponibles y no se conserva telemetría como si fuera actual.

Se crea un dispositivo controlador y un dispositivo por acumulador. El
controlador ofrece estado, potencia total, interruptor de control automático,
botón de recálculo y calendario global. Cada acumulador ofrece clima AUTO/OFF,
temperatura interior, SOC térmico, potencia, carga confirmada, posición de
compuerta opcional, próxima carga y próximo objetivo de SOC. El clima solo
permite AUTO/OFF y modifica la consigna semanal activa; no existe un mando
manual HEAT ni un mando de compuerta. El calendario agrupa intervalos contiguos
del mismo acumulador e incluye la evolución de SOC y energía.

La instalación se identifica por un UUID persistente del backend, no por el
nombre editable ni por el host. Por ello se conservan las entidades, nombres y
áreas al renombrar o reconfigurar el endpoint. La configuración detecta
duplicados por esa identidad y permite reautenticar el token sin crear otra
instalación.

## Despliegue en Docker

En la Raspberry prepara `/srv/app/data` para el estado persistente y configura
las variables de Compose. Los servicios backend se ejecutan con una identidad
numérica no root; por defecto es `1000:1000`, y se puede cambiar mediante
`DTC_RUNTIME_UID` y `DTC_RUNTIME_GID` si la instalación usa otra identidad:

```sh
export DTC_RUNTIME_UID=1000
export DTC_RUNTIME_GID=1000
export DTC_GPIO_GID="$(stat -c '%g' /dev/gpiochip0)"
sudo install -d -m 700 -o "$DTC_RUNTIME_UID" -g "$DTC_RUNTIME_GID" /srv/app/data
sudo chown -R "$DTC_RUNTIME_UID:$DTC_RUNTIME_GID" /srv/app/data
```

El `chown` solo es necesario al preparar la instalación o al migrar datos que
fueran creados por una versión anterior ejecutada como root. El reconciliador
detecta automáticamente el GID de `/dev/gpiochip0`; en un despliegue manual,
`DTC_GPIO_GID` debe ser el GID que devuelva `stat` para ese dispositivo.

En `/etc/app/app.env` debe existir el token administrativo que usará el panel:

```dotenv
DTC_API_TOKEN=un-token-aleatorio-de-al-menos-32-caracteres
```

El primer arranque lo guarda de forma no reversible y marca la instalación como
configurada; no se solicita ninguna credencial adicional de inicialización.

```sh
export DOCKERHUB_USERNAME=rromani
export APP_VERSION=VERSION
sudo -E docker compose -f deploy/compose.yaml pull
sudo -E docker compose -f deploy/compose.yaml up -d --remove-orphans --wait --wait-timeout 120
```

Los tres contenedores backend comparten `/srv/app/data` y ejecutan una
inicialización idempotente antes de arrancar. No hay que ejecutar comandos de
inicialización ni instalar Python, Node o servicios systemd en la Raspberry.

El frontend se publica en el puerto `80`. La API solo se expone dentro de la
red Docker y el panel la consume mediante nginx.

El servicio `backend` recibe `/dev/gpiochip0`, que es el dispositivo utilizado
por el driver `lgpio` para controlar las salidas, y monta el fichero de modelo
de la Raspberry en solo lectura. La lectura del modelo no necesita root; el
grupo adicional `DTC_GPIO_GID` es el que permite al usuario del proceso abrir
el dispositivo. En `Configuración → Servicio
→ Salidas físicas` selecciona `GPIO` como modo global y reinicia el controlador;
este cambio no se aplica a un proceso ya arrancado.

Los pines del acumulador se introducen como número GPIO, no como número físico
del conector ni como función alternativa. Por ejemplo, el pin físico 12 aparece
en muchos esquemas como `GPIO18 / PCM_CLK`: en la aplicación se debe configurar
como `18`. Para un LED que se enciende al llevar el GPIO a GND, el nivel activo
del acumulador debe ser `Bajo` (`active_high=false`).

La configuración se concentra en `/configuracion`, organizada por tareas. La
URL anterior `/configuracion-sistema` se conserva como alias y redirige a la
experiencia unificada.

La ruta `/prueba-reles` permite comprobar las salidas de los acumuladores con
una sesión exclusiva y temporal. Solo se puede iniciar con el controlador vivo
y una configuración válida; el panel muestra una salida como confirmada
únicamente cuando el controlador lo acredita, y mantiene la recuperación de
seguridad como responsabilidad del dispositivo. La duración, el sondeo y la
renovación de la sesión se ajustan en `Configuración → Servicio → Operación`.

La configuración de previsión se administra exclusivamente en `Configuración →
Integraciones → Meteorología`: allí se guardan proveedor, municipio AEMET, temperaturas simuladas y
de fallback, timeout y política de actualización. La clave AEMET se reemplaza
como secreto gestionado y la API solo informa si está configurada; nunca
devuelve su valor.

Para AEMET, `aemet_query_hour` define la consulta diaria en la zona horaria de
la instalación. Tras un fallo se realizan cinco reintentos, uno por hora; si
se agotan, el controlador conserva la última previsión AEMET válida marcada
como obsoleta para seguir calculando, pero nunca habilita carga automática con
una previsión simulada o de respaldo. `replan_minutes` marca la cadencia de
replanificación y se ajusta siempre a un límite de intervalo, sin ser menor que
un intervalo de carga.

La sección `Configuración → Integraciones → MQTT` permite desactivar el broker para instalaciones de
prueba. Mientras MQTT está deshabilitado, el controlador usa los dos valores
fijos globales de esa sección (temperatura interior y SOC almacenado); al
habilitarlo vuelve a exigir ambos datos recibidos por MQTT. La consigna térmica
procede del horario semanal configurado para cada acumulador y el proceso MQTT
del `Controller` la publica al `Heater` durante la descarga mediante el topic de
consigna configurado. El mando de descarga es una habilitación (`ON`/`OFF`), no
una orden de abrir permanentemente la compuerta: el termostato del acumulador
la modula contra esa consigna.

Con salidas GPIO, MQTT puede permanecer deshabilitado para realizar pruebas de
relés; cuando el controlador necesita planificar en ese modo usa los valores
fijos anteriores. La simulación explícita de acumuladores
(`mqtt_simulation_enabled`) sí bloquea el arranque GPIO y se registra como un
error crítico.

Cada acumulador puede configurar un único `telemetry_topic` MQTT. El payload es
un objeto JSON con las claves numéricas opcionales
`indoor_temperature_c`, `stored_soc_percent` y `damper_position_percent`; una
clave ausente conserva su último valor válido y una clave inválida solo
invalida ese campo. La telemetría agrupada no se retiene. Con la simulación
activa, el topic predeterminado es `<prefijo>/<id>/telemetry`, salvo que el
acumulador tenga uno configurado. El descubrimiento de Home Assistant agrupa
las entidades con la misma disponibilidad en un único mensaje por dispositivo;
las entidades que requieren además `state_available` mantienen su disponibilidad
individual.

### Alertas por email

El panel configura el envío de alertas en Configuración → Integraciones →
Alertas por email: activación, servidor SMTP, puerto, cifrado (`starttls`, `tls`
o ninguno), remitente, destinatarios y tiempo de espera. El usuario y la
contraseña SMTP se guardan como secretos de la configuración de sistema, igual
que la clave de AEMET y las credenciales MQTT, así que la API informa de si
están configurados pero nunca devuelve su valor; no hay ninguna variable de
entorno nueva. Activar el envío exige servidor, remitente y al menos un
destinatario, y las credenciales son opcionales porque un relé sin autenticación
es legítimo. Un botón envía un correo de prueba con la configuración vigente,
para no descubrir un servidor mal configurado la primera vez que hiciera falta
una alerta.

Cada tipo de alerta del catálogo se puede silenciar por separado. Un aviso se
envía **una vez por episodio**: al entrar en la condición y otra vez solo cuando
se ha resuelto y vuelve a ocurrir; el estado de rearme se persiste, así que un
reinicio no reenvía lo ya avisado. Los avisos se encolan de forma duradera y se
entregan desde el ciclo del controlador con reintentos y espera creciente, de
modo que sobreviven a un reinicio y un fallo de correo nunca interrumpe el
control ni el accionamiento de las salidas.

La primera alerta del catálogo avisa de una **replanificación imposible**: un
recálculo que devuelve `INVALID`. El correo identifica la instalación, el
instante, la causa y la consecuencia, que es quedarse sin plan activo cuando el
recálculo periódico lo desactiva.

### Topics MQTT de lectura y escritura

El prefijo MQTT de la instalación es `<prefijo>/installation` (por defecto,
`dtc/installation`). En la tabla, `Controller` significa el proceso MQTT de
esta aplicación; `Heater` significa el acumulador físico o su adaptador MQTT.
La dirección se expresa desde el punto de vista del `Controller`.

| Topic (ejemplo) | Emite | Recibe | Mensaje | QoS / retenido |
| --- | --- | --- | --- | --- |
| `ha/salon/telemetry` (`telemetry_topic` configurado) | `Heater` | `Controller` | JSON de telemetría | Suscripción QoS 1 / no retenido |
| `dtc/sim/salon/telemetry` (simulación sin topic propio) | Simulador del `Controller` | `Controller` | JSON de telemetría | QoS 0 / no retenido |
| `ha/salon/discharge` (`damper_topic` configurado) | `Controller` (proceso MQTT) | `Heater` | `ON` o `OFF` para habilitar/deshabilitar la descarga | QoS 1 / no retenido |
| `ha/salon/setpoint` (`setpoint_topic` configurado) | `Controller` (proceso MQTT) | `Heater` | Temperatura objetivo en °C, con un decimal; `NULL` si está desactivada | QoS 1 / no retenido |
| `dtc/installation/heater/salon/set/enabled` | Home Assistant u otro cliente MQTT | `Controller` | `ON` o `OFF` | El comando retenido se rechaza |
| `dtc/installation/availability` | `Controller` | Clientes MQTT / Home Assistant | `online` u `offline` | QoS 1 / retenido |
| `dtc/installation/state_available` | `Controller` | Clientes MQTT / Home Assistant | `online` u `offline` | QoS 1 / retenido |
| `dtc/installation/state` | `Controller` | Clientes MQTT / Home Assistant | Estado JSON de la instalación | QoS 1 / retenido |
| `dtc/installation/heater/salon/state` | `Controller` | Clientes MQTT / Home Assistant | Estado JSON del acumulador | QoS 1 / retenido |
| `homeassistant/device/dynamic_thermal_charge_installation/config` | `Controller` | Home Assistant | Configuración de discovery agrupada | QoS 1 / retenido |
| `homeassistant/device/dynamic_thermal_charge_installation_salon/config` | `Controller` | Home Assistant | Configuración de discovery agrupada del acumulador | QoS 1 / retenido |
| `homeassistant/<componente>/<unique_id>/config` | `Controller` | Home Assistant | Configuración de discovery individual | QoS 1 / retenido |

El topic de telemetría real de cada acumulador se configura en el panel; no se
deriva automáticamente de `<prefijo>/installation`. Su payload es un objeto
JSON con las claves numéricas opcionales `indoor_temperature_c`,
`stored_soc_percent` y `damper_position_percent`. Una clave ausente conserva su
último valor válido y una clave inválida solo invalida ese campo. La telemetría
no se retiene. Cuando la simulación está activa y no hay un topic configurado,
el topic es `<prefijo-de-simulación>/<id>/telemetry`.

Los topics `damper_topic` y `setpoint_topic` también se configuran por
acumulador en `Planificación → Nueva planificación`. El `Controller` publica
ambos mandos en cada ciclo, con QoS 1 y sin retención. Dentro de una ventana con
consigna activa publica `ON` y la temperatura objetivo, aunque ese intervalo
proyecte cero calor; el termostato del `Heater` puede cerrar la compuerta y
volver a abrirla según la temperatura interior. En una anticipación anterior,
si el plan proyecta calor entregado, publica `ON` y la próxima consigna. Al
terminar la ventana, o si no hay plan, el plan es `INVALID`, el control
automático está desactivado, el acumulador está en `OFF`, hay una prueba de
relés o el estado del `Controller` no es actual, publica `OFF` y no publica
consigna numérica: si `setpoint_topic` está configurado, publica `NULL` para que
el acumulador limpie su pantalla. Sin `damper_topic` no envía ninguno de los dos
mandos a ese acumulador y continúa con los demás.

#### Ejemplos de mensajes MQTT

Telemetría emitida por un acumulador real:

```text
Topic: ha/salon/telemetry
Payload: {"indoor_temperature_c":19.5,"stored_soc_percent":60,"damper_position_percent":42}
```

Telemetría emitida por el simulador del `Controller`:

```text
Topic: dtc/sim/salon/telemetry
Payload: {"indoor_temperature_c":45.0,"stored_soc_percent":50.0}
```

Mando de descarga y temperatura objetivo emitidos por el `Controller` al
`Heater`:

```text
Topic: ha/salon/discharge
Payload: ON

Topic: ha/salon/setpoint
Payload: 21.0
```

Cuando la descarga debe quedar desactivada, el mensaje es:

```text
Topic: ha/salon/discharge
Payload: OFF

Topic: ha/salon/setpoint
Payload: NULL
```

`NULL` es el sentinel de “sin consigna”; el `Heater` lo muestra como `--`.
Estos dos mensajes no son retenidos y se reafirman en cada ciclo; una parada
ordenada también publica `OFF` y `NULL`. El campo `discharge_enabled` del estado
del acumulador refleja el mando del `Controller`, mientras
`damper_position_percent`, si está presente, es la telemetría emitida por el
`Heater` y puede valer `0` aunque la descarga siga habilitada.

Comando de habilitación emitido por Home Assistant u otro cliente MQTT. No es
un comando del `Heater` ni contiene una consigna de temperatura:

```text
Topic: dtc/installation/heater/salon/set/enabled
Payload: ON
```

Disponibilidad publicada por el `Controller`:

```text
Topic: dtc/installation/availability
Payload: online
```

Disponibilidad del estado calculado por el `Controller`:

```text
Topic: dtc/installation/state_available
Payload: online
```

Snapshot de instalación publicado por el `Controller`:

```json
{
  "controller_health": "healthy",
  "forecast_average_c": 7.5,
  "forecast_source": "aemet",
  "instant_power_w": 2800,
  "multiple_controllers_suspected": false,
  "percent_of_limit": 53.8,
  "power_limit_w": 5200,
  "state_is_current": true,
  "window_end": "2026-01-16T08:00:00+00:00",
  "window_start": "2026-01-16T00:00:00+00:00"
}
```

El topic de ese mensaje es `dtc/installation/state`. Si el `Controller` no
puede acreditar que su estado sea actual, omite `instant_power_w`,
`percent_of_limit` y los campos de salida dependientes del controlador.

Snapshot de un acumulador publicado por el `Controller`:

```json
{
  "allocated_minutes": 270,
  "discharge_enabled": true,
  "enabled": true,
  "output_on": true,
  "power_w": 2800,
  "requested_minutes": 300,
  "unmet_minutes": 30
}
```

El topic de ese mensaje es `dtc/installation/heater/salon/state`.
`output_on` solo aparece cuando el estado del `Controller` es actual.

La consigna `target_temperature_c` se guarda como horario semanal y la usa el
planificador del `Controller`; no se incluye en `state` ni en
`heater/<id>/state`, sino que se publica como un número con un decimal en el
`setpoint_topic` del `Heater` mientras `discharge_enabled` sea `true`; cuando es
`false`, ese topic recibe `NULL`. El campo
heredado `target_temperature_topic` no se reutiliza para esta orden; sigue
siendo obsoleto junto con `temperature_topic`, `stored_charge_topic`,
`stored_soc_topic` e `indoor_topic`. La entrada actual de telemetría es el
único `telemetry_topic` agrupado.

El descubrimiento de Home Assistant se publica en
`<discovery_prefix>/device/<id-dispositivo>/config` para los dispositivos
agrupados. Por ejemplo, el dispositivo del controlador recibe un documento en
`homeassistant/device/dynamic_thermal_charge_installation/config` con este
fragmento representativo:

```json
{
  "dev": {
    "identifiers": ["dynamic_thermal_charge_installation"],
    "name": "Casa",
    "manufacturer": "Dynamic Thermal Charge"
  },
  "o": {"name": "Dynamic Thermal Charge"},
  "cmps": {
    "power_limit": {
      "name": "Límite de potencia",
      "unique_id": "dynamic_thermal_charge_installation_power_limit",
      "value_template": "{{ value_json.power_limit_w }}",
      "p": "sensor",
      "device_class": "power",
      "unit_of_measurement": "W"
    }
  },
  "state_topic": "dtc/installation/state",
  "availability": [{
    "topic": "dtc/installation/availability",
    "payload_available": "online",
    "payload_not_available": "offline"
  }]
}
```

El dispositivo del acumulador `salon` recibe además un documento en
`homeassistant/device/dynamic_thermal_charge_installation_salon/config` que
referencia `dtc/installation/heater/salon/state`:

```json
{
  "dev": {
    "identifiers": ["dynamic_thermal_charge_installation_salon"],
    "name": "Salón",
    "manufacturer": "Dynamic Thermal Charge",
    "via_device": "dynamic_thermal_charge_installation"
  },
  "o": {"name": "Dynamic Thermal Charge"},
  "cmps": {
    "power": {
      "name": "Potencia nominal",
      "unique_id": "dynamic_thermal_charge_installation_salon_power",
      "value_template": "{{ value_json.power_w }}",
      "p": "sensor",
      "device_class": "power",
      "unit_of_measurement": "W"
    }
  },
  "state_topic": "dtc/installation/heater/salon/state",
  "availability": [{
    "topic": "dtc/installation/availability",
    "payload_available": "online",
    "payload_not_available": "offline"
  }]
}
```

Los fragmentos anteriores muestran un componente; el documento real contiene
todos los componentes agrupados. Las entidades que dependen además de
`state_available` mantienen su discovery individual en
`<discovery_prefix>/<componente>/<unique_id>/config`. Por ejemplo, para la
salida del acumulador:

```json
{
  "name": "Salida",
  "unique_id": "dynamic_thermal_charge_installation_salon_output",
  "device": {
    "identifiers": ["dynamic_thermal_charge_installation_salon"],
    "name": "Salón",
    "manufacturer": "Dynamic Thermal Charge",
    "via_device": "dynamic_thermal_charge_installation"
  },
  "state_topic": "dtc/installation/heater/salon/state",
  "value_template": "{{ value_json.output_on }}",
  "availability": [
    {"topic": "dtc/installation/availability", "payload_available": "online", "payload_not_available": "offline"},
    {"topic": "dtc/installation/state_available", "payload_available": "online", "payload_not_available": "offline"}
  ],
  "availability_mode": "all",
  "payload_on": true,
  "payload_off": false
}
```

El topic de ese documento es
`homeassistant/binary_sensor/dynamic_thermal_charge_installation_salon_output/config`.
Estos topics los publica el `Controller` y no requieren suscripción externa.
Al eliminar una entidad, el `Controller` publica un payload vacío (`""`) en
su antiguo topic de discovery para retirarla de Home Assistant.

Si una salida rechaza una conmutación, el controlador degrada únicamente esa
salida: aplica el resto de las transiciones del ciclo, la reintenta en cada
sondeo y no persiste ninguna exclusión. Una salida cuyo apagado falla se sigue
considerando cerrada, de modo que la potencia instantánea no afirma un estado
que el driver no aceptó. Mientras alguna salida esté en esa situación el
controlador se publica como degradado y el fallo se registra como crítico una
sola vez por transición.

La sección `Configuración → Planificación` permite configurar la ventana visible y el
horizonte completo, ambos entre 1 y 48 horas, con ventana no mayor que el
horizonte, además del límite total de tiempo del optimizador en segundos
(entero positivo; por defecto 120). La sección `Planificación` consulta el plan aceptado en `GET /api/v1/planning`
y permite editar consignas semanales de temperatura y los topics `damper_topic`
(`ON`/`OFF`) y `setpoint_topic` (°C) de cada acumulador. La edición de esos
topics también está disponible en `PATCH /api/v1/planning/heaters/{heater_id}`;
un valor en blanco se guarda como ausente. Cada
consigna contiene temperatura en °C, hora de inicio, hora de fin y días de la
semana; el inicio se incluye, el fin se excluye y el intervalo puede cruzar
medianoche. La vista previa se inicia con
`POST /api/v1/planning/preview/jobs`, se consulta con
`GET /api/v1/planning/preview/jobs/{job_id}` y se cancela con
`POST /api/v1/planning/preview/jobs/{job_id}/cancel`; el trabajo y sus checks
se conservan al recargar. `POST /api/v1/planning/activate` valida el token de
inputs y guarda las consignas y el plan conjuntamente. Por defecto la ventana es
de 12 horas y el horizonte de 24 horas; ambos comienzan en el primer límite de
slot que no haya pasado (el límite exacto se conserva y los instantes
intermedios avanzan al siguiente). Sin cobertura AEMET horaria continua para todo el
horizonte no se publica un plan parcial. La
telemetría MQTT de cada acumulador se valida por separado y una muestra
incompleta o de más de 15 minutos se marca como caducada y deja ese acumulador
fuera del plan.

La planificación usa los estados públicos `VALID`, `CONVERGING`, `DEGRADED` e
`INVALID`. Solo `VALID` y `CONVERGING` pueden sustituir el plan activo; un
resultado `CONVERGING` se aplica desde el siguiente slot y muestra la hora en
que el modelo demuestra el cumplimiento continuado y hasta qué fin de horizonte
queda garantizado. Un `DEGRADED` se conserva como diagnóstico y mantiene el
último plan activable mientras tenga intervalos vigentes; `INVALID` bloquea la
activación y deja las salidas en estado seguro cuando no hay sustituto válido.
Los históricos que usaban `FEASIBLE` se leen como `VALID`. La configuración
incluye `deviation_shortfall_tolerance_c` (por defecto 0,1 °C) y
`deviation_surplus_soc_percent` (por defecto 5 %) para solicitar un recálculo
inmediato cuando la telemetría se desvía de la proyección; ambos valores deben
ser positivos.

La ventana y el horizonte se cuentan en horas de reloj de pared, y los límites de
slot caen siempre en múltiplos de la duración de slot configurada. Los dos días
del año en que cambia la hora, un horizonte de 24 horas cubre por tanto 25 horas
reales en octubre y 23 en marzo: con slots de 30 minutos son 50 y 46 slots en vez
de 48. Cada slot dura exactamente su duración configurada de tiempo real, los
límites nunca se solapan y la hora que se repite en octubre usa la previsión
horaria de esa hora de pared en sus dos pasadas.

El plan usa un balance físico por sala y por intervalo. En cada acumulador,
`room_thermal_capacity_kwh_per_c` (C) mide la energía necesaria para subir un
grado y `room_heat_loss_kw_per_c` (K) mide el intercambio con el exterior. La
pérdida firmada se calcula como `K × (temperatura interior − temperatura exterior)
× horas`; por eso puede ser negativa cuando fuera hace más calor. La capacidad
del almacén sigue siendo `potencia nominal × horas de carga completa`, y el SOC
recibido se convierte a kWh solo para inicializar esa energía. El plan muestra
por intervalo SOC, energía almacenada, temperatura interior, objetivo, calor
entregado, límite de emisión aplicado, intercambio térmico y déficit de
temperatura.

La capacidad de emisión de un acumulador decae con su estado de carga, porque su
núcleo se enfría a medida que se descarga. `full_discharge_hours` son las horas
de descarga nominal del fabricante y fijan la potencia máxima de emisión como
`capacidad kWh / horas de descarga`; `static_emission_percent` es la emisión que
conserva con la carga agotada, en porcentaje de esa máxima. El calor que puede
entregar un intervalo es
`(P_residual + (P_emisión − P_residual) × SOC) × horas del intervalo`, con el SOC
del borde inicial. Por eso un acumulador al 20% difícilmente sube la temperatura
de la estancia y puede no alcanzar la consigna aunque le quede energía: el plan
lo refleja como déficit y queda `DEGRADED` en vez de proyectar la emisión de un
acumulador lleno. La emisión residual es una capacidad, no una emisión forzada:
un acumulador vacío entrega cero. Fuera de las ventanas de consigna el calor
entregado es cero cuando ya no queda ninguna consigna por delante en el
horizonte; en los intervalos anteriores a una consigna la emisión sigue
permitida para poder precalentar.

Una consigna activa debe cumplirse en los dos bordes de cada slot: la temperatura
interior proyectada al comenzar y al terminar el intervalo debe alcanzar el
objetivo. El optimizador puede cargar y entregar calor en slots anteriores para
precalentar; si el objetivo ya está activo al inicio del horizonte, la temperatura
medida es su borde inicial y cualquier déficit inevitable se conserva como
`DEGRADED` con la hora exacta y el déficit proyectado. El fin de una consigna es
exclusivo, por lo que no se exige después de ese borde salvo que otra consigna
esté activa.

La interfaz etiqueta los valores térmicos y de energía con sus horas de inicio y
fin reales. La potencia de cada acumulador y la agregada se dibuja como ocupación
discreta del slot, sin rampas entre muestras. El gráfico de carga almacenada usa
un porcentaje común de 0 a 100 respecto a la capacidad configurada de cada
acumulador; el detalle conserva los kWh de inicio y fin para la auditoría física.
El eje vertical de temperatura se ajusta al rango de los datos representados.

Los valores iniciales recomendados son C = 2,5 kWh/°C y K = 0,12 kW/°C. No se
configuran objetivos porcentuales, reservas ni factores de demanda. Si falta
telemetría interior/SOC reciente, una consigna semanal, cobertura horaria o
potencia eléctrica suficiente, la vista previa lo declara como inválido o
degradado y no cambia al modelo porcentual anterior. La edición completa de un
acumulador se guarda con una única petición `PUT /api/v1/config/heaters/{id}`.

El histórico de decisiones está disponible en `GET /api/v1/history/planning-audit`
y conserva el motivo, el estado y las violaciones de cada preview o activación.
La misma vista proyecta el horizonte completo configurado y muestra la ventana
visible como sus intervalos iniciales; los gráficos muestran el contexto
de preview cuando existe y ofrecen una alternativa textual con unidades para
cada intervalo. El resumen usa lenguaje operativo y agrupa avisos por causa.

Para actualizaciones automatizadas, `deploy/reconcile.sh` lee `deploy/release`,
descarga las imágenes y aplica la versión indicada. El cronjob se instala con:

```sh
sudo /opt/app/repo/deploy/reconciler-cronjob.sh
```

La entrada se ejecuta cada cinco minutos y escribe únicamente actualizaciones o
errores, con timestamp, en `/opt/app/reconciler.log`. El reconciliador usa
`rromani` como usuario de Docker Hub, por lo que no necesita variables de
entorno adicionales.

## Desarrollo con Docker Compose

SQLite:

```sh
docker compose -f deploy/compose.dev.yaml up -d --build --wait
```

El panel queda en `http://localhost:8081`, la API en `http://localhost:8080` y
MQTT en `localhost:1883`. Configura `DTC_API_TOKEN` con al menos 32 caracteres
(si no se define, se usa un token de desarrollo que conviene rotar). Los datos
están aislados en `dev-state` y `dev-mosquitto-data`; reinícialos con `down -v`.

PostgreSQL:

```sh
docker compose -f deploy/compose.dev.yaml -f deploy/compose.dev-postgres.yaml up -d --build --wait
```

El bootstrap permanece en SQLite (`dev-postgres-state`) y PostgreSQL usa el
volumen `dev-postgres-data`; el entorno SQLite conserva sus datos en
`dev-sqlite-state`. Sus variables configurables son
`DTC_DEV_POSTGRES_HOST`, `DTC_DEV_POSTGRES_PORT`, `DTC_DEV_POSTGRES_DB`,
`DTC_DEV_POSTGRES_USER` y `DTC_DEV_POSTGRES_PASSWORD`.
Cada arranque conserva los datos existentes y aplica las migraciones pendientes
del esquema, igual que producción. Para borrar solo PostgreSQL usa
`docker compose -f deploy/compose.dev.yaml -f deploy/compose.dev-postgres.yaml down -v`.
