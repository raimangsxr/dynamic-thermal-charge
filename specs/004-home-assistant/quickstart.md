# Quickstart — Integración con Home Assistant

**Feature**: `004-home-assistant`

## Qué necesitas

- Un broker MQTT. Lo normal es que tu Home Assistant ya tenga Mosquitto instalado.
- Si Home Assistant no está en la misma red, un túnel —WireGuard u otro— que dé acceso al broker
  desde la Raspberry Pi. **Configurar el túnel queda fuera de este proyecto**; sobrevivir a que se
  caiga, no.

## Desarrollo local

```bash
python -m pip install -e '.[dev,mqtt]'

# Un broker de juguete, si no tienes otro a mano
docker run --rm -p 1883:1883 eclipse-mosquitto:2 \
  mosquitto -c /mosquitto-no-auth.conf

export DTC_DATABASE_URL="sqlite:///$(pwd)/var/dtc.db"
export DTC_MQTT_HOST=127.0.0.1

dtc db upgrade        # aplica la revisión 0003
dtc mqtt              # el publicador
```

Para ver qué se publica, sin Home Assistant:

```bash
mosquitto_sub -h 127.0.0.1 -t 'homeassistant/#' -t 'dtc/#' -v
```

Y las pruebas, que no necesitan ningún broker:

```bash
pytest        # sin red, sin broker, sin Home Assistant, sin hardware
```

## Conectar a un Home Assistant remoto por WireGuard

El publicador no sabe nada del túnel: se conecta a la dirección que le des. Con WireGuard en
marcha, esa dirección es la del broker dentro de la red del túnel.

```bash
# En /etc/dynamic-thermal-charge/environment
DTC_MQTT_HOST=10.6.0.1          # la dirección del broker DENTRO del túnel
DTC_MQTT_PORT=1883
DTC_MQTT_USERNAME=dtc
DTC_MQTT_PASSWORD=...
```

**Sobre el cifrado**: si el broker se alcanza **por el túnel**, WireGuard ya cifra el tránsito y
activar TLS sobre MQTT es redundante. Si lo alcanzas por una red que no controlas, no lo es:

```bash
DTC_MQTT_TLS=true
DTC_MQTT_PORT=8883
```

La decisión es tuya porque depende de tu despliegue; el proyecto ofrece las dos.

### Qué pasa cuando el túnel se cae

Nada que requiera intervención:

- El publicador reintenta con espera creciente, de 1 s hasta 120 s, y **no termina el proceso**.
- El broker publica la última voluntad, y Home Assistant marca **todas** las entidades como no
  disponibles. No se queda mostrando el último valor conocido.
- Al volver, el publicador republica el descubrimiento y después el estado, en ese orden, y Home
  Assistant recupera todo solo.
- **El controlador no se entera.** Sigue ejecutando su plan; el publicador es otro proceso.

## Qué aparece en Home Assistant

Un dispositivo por instalación y uno por acumulador, sin escribir una línea de configuración en
Home Assistant.

**Por acumulador**: salida activa, potencia nominal, habilitado *(conmutable)*, carga objetivo
*(ajustable)*, minutos solicitados, asignados y no atendidos, temperatura interior en uso, y si está
usando la reserva térmica.

**Por instalación**: potencia instantánea y su porcentaje del límite, límite configurado, ventana del
plan, temperatura media prevista, origen de la previsión, salud del controlador, y un aviso de
sospecha de más de un controlador.

### Por qué a veces aparecen como «no disponible»

Porque no hay prueba de lo contrario, y eso es deliberado:

| Situación | Qué queda no disponible |
| --- | --- |
| el publicador está parado, o el túnel caído | **todo** |
| el controlador no está visible | salida activa y potencia instantánea; la configuración sigue visible |
| la base de datos no responde | todo, y se registra el motivo |

Un `binary_sensor` mostrando «apagado» cuando en realidad nadie puede confirmarlo es peor que uno
no disponible: el primero engaña a una automatización, el segundo la detiene.

## Automatizar desde Home Assistant

Home Assistant puede cambiar **dos** cosas, y ninguna acciona un relé: cambian la configuración y
el planificador decide.

```yaml
# Bajar la carga del salón si va a hacer menos frío de lo previsto
automation:
  - alias: Salón a media carga
    trigger:
      - platform: numeric_state
        entity_id: sensor.dtc_temperatura_media_prevista
        above: 12
    action:
      - action: number.set_value
        target: { entity_id: number.salon_carga_objetivo }
        data: { value: 0.5 }
```

**Lo que Home Assistant NO puede cambiar**: potencia máxima simultánea, asignación de pines y nivel
activo. Están fuera de su alcance por construcción, no por comprobación: el publicador solo admite
esos dos campos, con lista blanca.

Si envías una orden inválida, se rechaza, se registra el motivo, y la entidad **vuelve al valor
realmente almacenado**. Si te quedas mirando el valor que ordenaste, es un fallo.

## Cerrar el lazo con la temperatura real

Sin esto, el modelo asume que cada estancia está a su temperatura objetivo y calcula solo a partir
de la previsión exterior. Con esto, usa la medida real: una estancia que ya está caliente deja de
cargarse como si estuviera fría.

**Paso 1** — que Home Assistant publique sus sensores en MQTT. Con el reenvío de estados es una vez
para todos:

```yaml
mqtt_statestream:
  base_topic: ha
  publish_attributes: false
  include:
    entities:
      - sensor.temperatura_salon
      - sensor.temperatura_entrada
```

**Paso 2** — declarar el asunto de cada acumulador:

```bash
dtc config set indoor_topic ha/sensor/temperatura_salon/state --heater salon
```

También desde el panel web o desde la API, como cualquier otro campo.

**Paso 3** — ajustar la tolerancia si tus sensores publican despacio:

```bash
dtc config set indoor_max_age_minutes 30      # por defecto
dtc config set indoor_min_plausible_c -20
dtc config set indoor_max_plausible_c 50
```

### La reserva, y cuándo actúa

Un acumulador **sin** `indoor_topic` declarado se comporta **exactamente** como antes de esta fase.
Eso está probado, no supuesto.

Con `indoor_topic` declarado, el modelo vuelve al comportamiento anterior si:

- no ha llegado ninguna medida;
- la última llegó hace más de `indoor_max_age_minutes` — media hora por defecto, porque una
  temperatura de hace seis horas no es una medida;
- el valor está fuera del rango plausible, que es lo que publica un sensor con un cable roto.

Cada entrada y salida de la reserva se registra **una vez**, no en cada cálculo. Un valor
implausible se registra como error, porque indica un sensor averiado y no una ausencia normal.

## Desplegar en la Raspberry Pi

```bash
sudo ./scripts/install-service.sh --with-api --with-panel --with-mqtt
sudoedit /etc/dynamic-thermal-charge/environment   # DTC_MQTT_HOST y credenciales

sudo -u dynamic-thermal-charge \
  /opt/dynamic-thermal-charge/venv/bin/dtc db upgrade

sudo systemctl start dynamic-thermal-charge-mqtt
```

Cuatro servicios independientes. Merece la pena comprobarlo una vez:

```bash
sudo systemctl stop dynamic-thermal-charge-mqtt   # la calefacción sigue igual
```

El publicador **no** pertenece al grupo `gpio`: no puede alcanzar el hardware ni queriendo.

## Diagnóstico

| Síntoma | Causa probable |
| --- | --- |
| no aparece ninguna entidad en HA | el prefijo de descubrimiento no coincide con el de HA, o la integración MQTT de HA no está configurada |
| todas las entidades «no disponibles» | el publicador está parado, o no alcanza el broker: `systemctl status dynamic-thermal-charge-mqtt` |
| solo salida y potencia «no disponibles» | correcto por diseño: el controlador no está visible; revisa su unidad |
| entidades duplicadas o huérfanas tras renombrar | el identificador cambió; los nuestros son estables, así que sospecha de un cambio de prefijo |
| una orden no tiene efecto y la entidad vuelve atrás | fue rechazada; el motivo está en los registros del publicador |
| el aviso de más de un controlador | revísalo: dos procesos sobre los mismos relés es un riesgo eléctrico |
| «usando reserva térmica» siempre activo | no llega la medida, llega vieja, o es implausible; los registros dicen cuál |
| reintentos de conexión sin fin | credenciales incorrectas se registran de forma distinta a un broker inalcanzable; mira cuál es |
| tras actualizar, HA no ve las entidades | `dtc db upgrade` pendiente: el publicador no publica sobre un esquema que no comprende |
