# Contract — Mensajería con Home Assistant

**Feature**: `004-home-assistant`

Prefijo configurable; los ejemplos usan `dtc` para los asuntos propios y `homeassistant` para el
descubrimiento, que es el que Home Assistant observa por defecto.

## Variables de entorno

| Variable | Obligatoria | Por defecto | Descripción |
| --- | :---: | --- | --- |
| `DTC_DATABASE_URL` | sí | — | Sin cambios |
| `DTC_MQTT_HOST` | sí | — | Dirección del broker. Puede ser una del túnel |
| `DTC_MQTT_PORT` | no | `1883` | `8883` con cifrado |
| `DTC_MQTT_USERNAME` | no | — | Credenciales del broker |
| `DTC_MQTT_PASSWORD` | no | — | Nunca en la base de datos ni en los logs |
| `DTC_MQTT_TLS` | no | `false` | Cifrado de la conexión al broker |
| `DTC_MQTT_PREFIX` | no | `dtc` | Prefijo de los asuntos propios |
| `DTC_MQTT_DISCOVERY_PREFIX` | no | `homeassistant` | El que observa Home Assistant |
| `DTC_MQTT_PUBLISH_SECONDS` | no | `15` | Cadencia de publicación de estado |

El publicador **falla el arranque** si falta `DTC_MQTT_HOST`, y **no** si el broker está
inalcanzable: eso es un reintento, no un error de configuración.

## Asuntos

```text
dtc/<instalación>/availability                 último nivel 1: online / offline
dtc/<instalación>/state_available              nivel 2: online / offline
dtc/<instalación>/state                        JSON con el estado de la instalación
dtc/<instalación>/heater/<id>/state            JSON con el estado del acumulador

dtc/<instalación>/heater/<id>/set/enabled      MANDO: ON / OFF
dtc/<instalación>/heater/<id>/set/target_charge MANDO: 0..1

<lo que se configure por acumulador>           ENTRADA: temperatura interior
```

Retención:

| Asunto | Retenido | Por qué |
| --- | :---: | --- |
| descubrimiento | **sí** | Home Assistant recupera las entidades al reiniciarse |
| `availability`, `state_available` | **sí** | el estado de disponibilidad debe sobrevivir a un reinicio de HA |
| `state`, `heater/*/state` | **sí** | HA muestra el último valor conocido en cuanto se suscribe |
| `set/*` | **NO** | una orden retenida se reentregaría al reconectar, reaplicando una orden vieja |

Esa última fila es la que importa. Con retención en los asuntos de mando, un túnel que vuelve tras
tres días deshabilitaría un acumulador porque alguien lo pidió entonces.

## Última voluntad

Se declara **antes de conectar**, con retención:

```text
topic:   dtc/<instalación>/availability
payload: offline
retain:  true
qos:     1
```

Declararla después de conectar no sirve de nada, y no lo detectaría ningún test ingenuo. Es lo que
convierte una muerte silenciosa del proceso —o una caída del túnel— en entidades no disponibles en
lugar del último valor congelado para siempre.

Al conectar se publica `online` en el mismo asunto.

## Disponibilidad en dos niveles

Cada entidad declara su disponibilidad así:

```jsonc
// Entidad que depende de ver al controlador (estado de salida, potencia):
"availability_mode": "all",
"availability": [
  { "topic": "dtc/casa/availability",      "payload_available": "online", "payload_not_available": "offline" },
  { "topic": "dtc/casa/state_available",   "payload_available": "online", "payload_not_available": "offline" }
]

// Entidad que solo necesita al publicador (configuración, límite, salud):
"availability": [
  { "topic": "dtc/casa/availability",      "payload_available": "online", "payload_not_available": "offline" }
]
```

`state_available` se publica `offline` cuando la API informa de que el estado no es vigente, y
`online` cuando lo es. Con eso, un controlador muerto y un publicador vivo produce exactamente lo
correcto: salidas y potencia no disponibles, configuración y salud del controlador visibles.

## Descubrimiento

Un dispositivo por instalación y uno por acumulador, agrupados con el mismo identificador de
dispositivo para que Home Assistant los presente juntos.

```jsonc
// dtc/casa/heater/salon/state es el objeto del que salen los valores
{
  "name": "Salida",
  "unique_id": "dtc_casa_salon_output",     // estable entre reinicios
  "device": {
    "identifiers": ["dtc_casa_salon"],
    "name": "Salón",
    "manufacturer": "Dynamic Thermal Charge",
    "via_device": "dtc_casa"
  },
  "state_topic": "dtc/casa/heater/salon/state",
  "value_template": "{{ value_json.output_on }}",
  "payload_on": true,
  "payload_off": false,
  "availability_mode": "all",
  "availability": [ /* los dos niveles */ ]
}
```

`unique_id` se deriva de la instalación y del **identificador de dominio** del acumulador, nunca de
una clave interna ni de un orden. Si cambiara, las automatizaciones ya escritas dejarían de
funcionar sin ningún aviso.

Al eliminarse un acumulador se publica un mensaje **vacío y retenido** en su asunto de
descubrimiento: así Home Assistant borra la entidad en lugar de conservar una huérfana.

## Orden al reconectar

```text
1. publicar availability = online
2. republicar TODO el descubrimiento
3. publicar el estado
```

Ese orden no es cosmético. Al revés, Home Assistant recibiría estado de entidades que para él
todavía no existen y lo descartaría en silencio.

## Órdenes: lista blanca de dos

| Asunto | Carga admitida | Se aplica como |
| --- | --- | --- |
| `set/enabled` | `ON` / `OFF` | `set_field(enabled)` |
| `set/target_charge` | número entre 0 y 1 | `set_field(target_charge)` |

Todo lo demás se rechaza y se registra. Es una **lista blanca**: un campo nuevo queda fuera por
defecto, no por omisión de haber pensado en él.

Cada orden se aplica con el repositorio de configuración —misma validación, misma atomicidad, mismo
bloqueo optimista que la CLI, la API y el panel—, con **un** reintento ante conflicto de revisión.
Reintentar indefinidamente convertiría una orden en un bucle contra el panel web.

Tras aplicar o rechazar, se **republica el estado del acumulador**, de modo que la entidad refleje
el valor realmente almacenado y no el ordenado.

## Temperatura interior

El publicador se suscribe al asunto que cada acumulador declare en su configuración. Del lado de
Home Assistant basta el reenvío de estados o una automatización de dos líneas por sensor.

Del mensaje se toma **solo el número**. Si trae una fecha, se ignora: la antigüedad se mide con el
instante en que este dispositivo recibió el mensaje.

```text
valor no numérico o vacío          -> se descarta con registro
fuera del rango plausible          -> se descarta con registro de error
más antiguo que la tolerancia      -> se trata como ausente
en otro caso                       -> se usa en el modelo térmico
```

## Lo que el publicador NO hace

- **No** acciona ninguna salida, ni directa ni indirectamente. Su paquete no importa nada capaz de
  hacerlo, y una guardia estática lo verifica.
- **No** acepta órdenes sobre potencia máxima, pin ni nivel activo.
- **No** migra el esquema ni inicializa la base de datos.
- **No** guarda credenciales de Home Assistant: no las necesita.
- **No** publica datos cuando la base de datos no responde: marca las entidades no disponibles.
