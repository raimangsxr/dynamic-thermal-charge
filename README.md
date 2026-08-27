# Dynamic Thermal Charge

Planificador configurable de carga para acumuladores eléctricos, pensado para
funcionar en una Raspberry Pi 2B sin acoplar la lógica de negocio al hardware.

El proyecto carga una instalación desde **base de datos**, obtiene la predicción
meteorológica, calcula la demanda mediante un modelo térmico y crea un plan por
intervalos respetando el límite de potencia. Guarda además un histórico auditable
de planes, previsiones y transiciones de salida. Incluye un controlador
persistente con salidas simuladas y un driver GPIO real aislado del núcleo de
planificación.

El desarrollo se rige por la [constitución del proyecto](.specify/memory/constitution.md)
y por Spec-Driven Development; la especificación de la configuración en base de
datos está en [`specs/001-config-database/`](specs/001-config-database/).

## Requisitos

- Python 3.12 o superior
- Sin dependencias de runtime obligatorias. La persistencia vive en el extra
  opcional `db` (SQLAlchemy y Alembic), y PostgreSQL en el extra `postgres`
  (`pg8000`).

## Puesta en marcha

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

export DTC_DATABASE_URL="sqlite:///$(pwd)/var/dtc.db"
dtc db init          # crea el esquema y siembra la instalación de ejemplo
dtc config show      # revisa qué se ha sembrado
dtc run              # planifica
pytest
```

`dtc` y `dynamic-thermal-charge` son el mismo ejecutable; los ejemplos usan el
corto. También puede ejecutarse sin instalar el comando:

```bash
PYTHONPATH=src python -m dynamic_thermal_charge config show
```

## Configuración

## Prueba manual de relés

El panel autenticado incluye **Prueba de relés** para diagnosticar acumuladores
configurados. Es una sesión temporal y exclusiva: la API solo guarda intención;
el controlador es el único proceso que conmuta GPIO y la interfaz no presenta un
estado como físico hasta que el driver lo confirma.

Al iniciar se entrega una credencial de cliente de un solo uso visual, guardada
únicamente en `sessionStorage`. Además del token normal de API, esa credencial es
necesaria para ordenar, renovar o finalizar la sesión. No debe copiarse a URLs,
logs ni almacenamiento persistente. Una pestaña sin ella es solo observadora.

Finalizar, caducar el lease, reiniciar el controlador o perder coordinación
provoca un barrido OFF de todas las salidas. Si una no confirma OFF se mantiene
un *fault latch* persistente: bloquea automático, nuevas pruebas y cambios de
configuración. No existe un botón HTTP para limpiarlo; solo el controlador lo
retira tras un barrido OFF completo y el automático vuelve en un ciclo posterior.
La pantalla muestra tanto esta recuperación como una auditoría degradada. La
auditoría es best-effort y nunca bloquea una conmutación de seguridad.

La consulta por identificador de sesión conserva el desenlace terminal mientras
la política de retención lo permita. Antes de un downgrade de la migración 0004
debe no haber sesión ni latch activos y verificarse OFF de las cargas.

Para validar el modo sin hardware use las tres suites del proyecto:

```bash
pytest
npm --prefix frontend run test
npm --prefix frontend run build
```

La configuración vive en base de datos. **No hay fichero de configuración**: el
runtime no lee ningún YAML. `examples/home.yaml` y `examples/raspberry-pi.yaml`
se conservan solo como documentación de los campos disponibles y como referencia
de la instalación que siembra `dtc db init`.

### Dónde está la base de datos

La ubicación se lee de la variable de entorno `DTC_DATABASE_URL`. Es el único
sitio donde vive, y nunca se escribe en la propia base de datos, en el
repositorio ni en los logs.

```bash
# Base de datos local, en el propio dispositivo
export DTC_DATABASE_URL="sqlite:////var/lib/dynamic-thermal-charge/dynamic-thermal-charge.db"

# Base de datos remota
export DTC_DATABASE_URL="postgresql+pg8000://dtc:CLAVE@servidor:5432/dtc"
```

Se admiten exactamente dos motores: **SQLite** local y **PostgreSQL** remoto, con
comportamiento idéntico entre ambos. PostgreSQL es siempre externo al
dispositivo: instalar un motor de base de datos en una Raspberry Pi 2B queda
descartado por recursos. El driver es `pg8000`, Python puro, el único instalable
en ARMv7 sin compilador ni `libpq`; se instala con el extra `postgres`.

En los logs de arranque se registra el motor, si es local o remoto, el host y el
nombre de la base de datos. **Nunca la cadena de conexión**, ni enmascarada.

### Inicializar y migrar

```bash
dtc db init             # crea el esquema, migra si hace falta, siembra si está vacía
dtc db init --no-seed   # crea y migra, pero no siembra nada
dtc db upgrade          # solo migraciones pendientes; nunca siembra
```

`db init` es idempotente: se puede repetir sin miedo y no sobrescribe una
configuración existente. El esquema está versionado; si la base de datos tiene
una revisión **posterior** a la que el servicio comprende, el arranque se rechaza
en lugar de operar sobre datos que no entiende.

### Ver y editar

```bash
dtc config show
dtc config show --heater salon

dtc config set max_total_power_kw 5.2
dtc config set slot_minutes 30
dtc config set start_time 00:00
dtc config set end_time 08:00
dtc config set retention_days 365
dtc config set target_charge 0.8 --heater salon
dtc config set enabled false --heater buhardilla

dtc config add-heater cocina \
  --power-kw 1.2 --full-charge-hours 7 \
  --output gpio --pin 24 --no-active-high \
  --target-temperature-c 20 --design-outdoor-temperature-c -2

dtc config remove-heater cocina --yes
```

Cada cambio se valida contra la **configuración completa resultante** antes de
aplicarse. Un cambio que dejaría la instalación inválida no se aplica y el error
dice qué campo lo impide:

```console
$ dtc config set slot_minutes 45
error: slot_minutes must be a divisor of 60

$ dtc config set pin 17 --heater entrada
error: heater entrada: pin 17 is already assigned to heater 'salon'
```

Las ediciones son atómicas y usan bloqueo optimista: si otro proceso cambió la
configuración mientras preparabas la tuya, la segunda se rechaza en lugar de
perder la primera en silencio. Los valores con aspecto de credencial o de cadena
de conexión se rechazan en cualquier campo.

Campos principales:

- `max_total_power_kw`: potencia máxima simultánea dedicada a acumuladores.
- `slot_minutes`: resolución del plan. Debe ser divisor de 60.
- `window_hours` / `window_minutes`: duración de la ventana de carga.
- `full_charge_hours`: tiempo que necesita el aparato para una carga completa.
- `target_charge`: fracción de carga solicitada (`0..1`).
- `priority`: los valores mayores se atienden primero cuando falta capacidad.
- `retention_days`: días de histórico conservados; `none` para ilimitado.

### Histórico y retención

La base de datos guarda cada plan generado con su ventana, sus intervalos y los
minutos solicitados no atendidos; cada previsión utilizada, indicando si vino del
proveedor real o del valor de reserva; y cada transición de encendido y apagado
de cada salida. Con eso se reconstruye una noche completa sin depender de los
logs del sistema.

```bash
dtc history prune
```

La limpieza elimina lo anterior a `retention_days` y **nunca** toca la
configuración ni un plan vivo: cualquier plan cuya ventana aún no haya terminado
queda protegido, incluidos los ya calculados para mañana. La auditoría de
cambios de configuración queda excluida de la retención a propósito: es la única
traza de quién cambió qué, y son decenas de filas al año.

Un año de funcionamiento con cuatro acumuladores son del orden de 27 000 filas,
unos pocos megabytes. El valor por defecto es 365 días.

### Perfil térmico

En una instalación real, un perfil térmico sustituye el porcentaje manual:

```bash
dtc config set target_temperature_c 21.0 --heater salon
dtc config set design_outdoor_temperature_c -2.0 --heater salon
dtc config set thermal_factor 1.0 --heater salon
dtc config set min_charge 0.10 --heater salon
dtc config set max_charge 1.0 --heater salon
```

El motor calcula una fracción lineal entre la temperatura exterior media de
diseño (carga completa) y la temperatura objetivo (sin carga), aplica el factor
térmico de la estancia y respeta los límites configurados. Un perfil térmico
exige un proveedor meteorológico configurado.

### AEMET OpenData

La instalación sembrada usa la predicción diaria de AEMET por municipio:

```bash
dtc config set provider aemet
dtc config set municipality_code 15057
dtc config set api_key_env AEMET_API_KEY
dtc config set timeout_seconds 10
dtc config set fallback_average_temperature_c 8.0
dtc config set fallback_minimum_temperature_c 3.0
```

`municipality_code` debe ser el código INE de cinco dígitos de la vivienda. La
API key **no se guarda nunca en la base de datos**: la configuración almacena
solo el *nombre* de la variable de entorno de la que leerla.

```bash
export AEMET_API_KEY='clave-obtenida-en-AEMET-OpenData'
dtc run
```

El cliente solicita primero el recurso de predicción y después la URL segura
de datos devuelta por AEMET. Para cada fecha obtiene mínima y máxima y usa su
media en el motor térmico. Ante ausencia de credenciales, error HTTP, timeout o
respuesta inválida, se registra un `WARNING` y se emplean los valores de
fallback. Como AEMET no siempre hace coincidir el charset anunciado con el
cuerpo, el cliente prueba primero UTF-8 y admite después su codificación
heredada ISO-8859-15. El proveedor `simulated` sigue disponible para pruebas
deterministas.

Cada ejecución registra a nivel `INFO` la fecha, proveedor, municipio (cuando
lo proporciona AEMET) y temperaturas mínima, media y máxima utilizadas por el
motor térmico. Si se activa el fallback, el campo `source` muestra
`simulated`.

### Watchdog meteorológico

Para producción, el modo persistente mantiene viva la supervisión de la
previsión:

```bash
dtc run --watch-weather
```

Sus intervalos se configuran en minutos:

```bash
dtc config set retry_minutes 15
dtc config set refresh_minutes 180
```

Si AEMET falla, el primer plan se crea inmediatamente con el fallback y el
proceso reintenta el proveedor primario cada `retry_minutes`. Cuando AEMET se
recupera, registra la recuperación y recalcula el plan con la predicción real.
Mientras el proveedor funciona, renueva la previsión y el plan cada
`refresh_minutes`. `Ctrl+C` detiene el watchdog de forma limpia.

### Controlador persistente

El controlador ejecuta el plan activo contra el driver simulado:

```bash
dtc run --controller
```

Su estado se configura de forma independiente:

```bash
dtc config set state_file /var/lib/dynamic-thermal-charge/active-plan.json
dtc config set poll_seconds 5
```

El plan activo conserva una **copia local en fichero** además de quedar
registrado en la base de datos. Son dos cosas distintas a propósito: la base de
datos es la auditoría, y el fichero es lo que permite reanudar el plan tras un
reinicio aunque la base de datos remota esté inalcanzable en ese momento. Sin
esa copia, un corte de red en el arranque significaría una noche sin
calefacción.

El servicio fuerza todas las salidas a OFF al arrancar, guarda cada plan nuevo
de forma atómica y recupera el último plan válido tras un reinicio. Comprueba el
slot activo cada `poll_seconds` y solo genera acciones cuando cambia el estado.
Ante un fallo de actualización conserva el último plan persistido; si no hay
ninguno válido mantiene todas las salidas apagadas. Al recibir `Ctrl+C` o una
excepción fuerza de nuevo todas las salidas a OFF.

Sin indicar nada más, `--controller` utiliza `SimulatedOutputDriver`, aunque la
configuración declare salidas GPIO. El hardware real solo se habilita de forma
explícita con `--driver gpio`.

Si la base de datos deja de responder con el servicio en marcha, el plan en
curso se sigue ejecutando y el proceso reintenta con la cadencia configurada,
registrando la degradación una sola vez al entrar y otra al salir. Si la
configuración almacenada resulta inválida, el refresco se abandona con un log
crítico y el plan persistido se agota; a partir de ahí todas las salidas quedan
apagadas. Un fallo al escribir el histórico se registra como error y no
interrumpe ni la planificación ni la conmutación.

## Instalación como servicio systemd

En Raspberry Pi OS con Python 3.12, ejecutar desde el repositorio:

```bash
sudo ./scripts/install-service.sh
```

El instalador crea un usuario sin shell, un entorno virtual aislado y estas
rutas:

- `/opt/dynamic-thermal-charge/venv`: aplicación instalada, con el extra `db`.
- `/etc/dynamic-thermal-charge/environment`: `DTC_DATABASE_URL` y `AEMET_API_KEY`,
  modo `0600`, conservado en las actualizaciones.
- `/var/lib/dynamic-thermal-charge/dynamic-thermal-charge.db`: base de datos
  local, si se usa SQLite.
- `/var/lib/dynamic-thermal-charge/active-plan.json`: caché del último plan
  válido.

El instalador **no arranca ni habilita** el servicio, y **no inicializa** la base
de datos por ti: imprime al terminar el único comando que debes ejecutar.

```bash
sudoedit /etc/dynamic-thermal-charge/environment   # DTC_DATABASE_URL y AEMET_API_KEY

set -a; . /etc/dynamic-thermal-charge/environment; set +a
sudo -u dynamic-thermal-charge \
  /opt/dynamic-thermal-charge/venv/bin/dtc db init
sudo -u dynamic-thermal-charge \
  /opt/dynamic-thermal-charge/venv/bin/dtc config show   # revisar campo por campo

sudo systemctl start dynamic-thermal-charge
sudo systemctl enable dynamic-thermal-charge
```

### Actualizar desde una versión con fichero de configuración

**La configuración no se migra: no existe importación automática.** Fue una
decisión deliberada de esta fase, y hay que reintroducir la instalación a mano.

El instalador detecta un `config.yaml` previo, lo conserva como
`/etc/dynamic-thermal-charge/config.yaml.pre-database` y **no siembra** la
instalación de ejemplo, para no interponer datos de ejemplo entre tú y la
configuración real que vas a reproducir.

Procedimiento:

1. Detén el servicio: `sudo systemctl stop dynamic-thermal-charge`.
2. Guarda una copia del YAML vigente antes de actualizar:
   `sudo cp /etc/dynamic-thermal-charge/config.yaml ~/config.yaml.bak`.
3. Actualiza y define `DTC_DATABASE_URL` en el fichero de entorno.
4. Crea la base de datos vacía: `dtc db init --no-seed`.
5. Con la copia delante, reproduce la instalación con `dtc config set` y
   `dtc config add-heater`. Presta especial atención a **los pines BCM,
   `active_high` y la potencia máxima**: un error aquí se paga en el cuadro
   eléctrico.
6. Verifica con `dtc config show` **campo por campo** contra la copia.
7. Antes de arrancar con hardware real, repite el autotest de LEDs de más abajo.

El servicio no arranca sin una configuración válida y no activa ninguna salida
mientras no la tenga, así que un olvido se manifiesta como servicio parado, nunca
como un relé cerrado por error.

Operación y diagnóstico:

```bash
systemctl status dynamic-thermal-charge
journalctl -u dynamic-thermal-charge -f
sudo systemctl restart dynamic-thermal-charge
sudo systemctl stop dynamic-thermal-charge
```

La unidad valida la configuración antes de arrancar, espera a que red y reloj
estén disponibles, reinicia el proceso tras fallos y aplica restricciones de
seguridad de systemd. `SIGTERM` se transforma en una parada controlada para que
el controlador apague las salidas en su bloque `finally`. La instalación no
habilita ni arranca automáticamente el servicio y continúa usando salidas
simuladas.

## Home Assistant mediante MQTT

El publicador es un cuarto servicio independiente: no pertenece al grupo
`gpio`, no importa drivers y no puede conmutar salidas. Home Assistant descubre
automáticamente un dispositivo de instalación y uno por acumulador:

- por instalación: potencia instantánea y porcentaje del límite, límite,
  ventana, previsión y origen, salud del controlador y sospecha de procesos
  duplicados;
- por acumulador: salida, potencia nominal, habilitación, carga objetivo y
  minutos solicitados, asignados y no atendidos.

Los identificadores usan el segmento fijo `installation` y el id de dominio del
acumulador. Renombrar la instalación o cambiar `DTC_MQTT_PREFIX` no cambia los
`unique_id` ni rompe automatizaciones.

### Configurar y arrancar

```bash
python -m pip install -e '.[dev,mqtt]'
export DTC_DATABASE_URL="sqlite:///$(pwd)/var/dtc.db"
export DTC_MQTT_HOST=127.0.0.1
dtc db upgrade
dtc mqtt
```

Para la Raspberry Pi:

```bash
sudo ./scripts/install-service.sh --with-mqtt
sudoedit /etc/dynamic-thermal-charge/environment
sudo systemctl start dynamic-thermal-charge-mqtt
```

El instalador no migra, arranca ni habilita servicios. Las variables disponibles
son `DTC_MQTT_HOST`, `DTC_MQTT_PORT` (1883), `DTC_MQTT_USERNAME`,
`DTC_MQTT_PASSWORD`, `DTC_MQTT_TLS` (false), `DTC_MQTT_PREFIX` (`dtc`),
`DTC_MQTT_DISCOVERY_PREFIX` (`homeassistant`) y
`DTC_MQTT_PUBLISH_SECONDS` (15). La contraseña solo vive en el fichero de
entorno de modo `0600`; nunca se guarda en la base de datos ni se registra.

Un broker remoto puede alcanzarse por WireGuard u otro túnel usando su dirección
dentro del túnel. Si el transporte no está ya cifrado, activa TLS y normalmente
el puerto 8883:

```bash
DTC_MQTT_HOST=10.6.0.1
DTC_MQTT_PORT=8883
DTC_MQTT_TLS=true
```

La conexión usa MQTT v5. Descubrimiento, disponibilidad y estado se publican
retenidos con QoS 1 y solo cuentan como correctos tras un PUBACK aceptado. Las
ACL mínimas del usuario del broker son:

- publicar en `homeassistant/#` y `dtc/installation/#`;
- suscribirse a `dtc/installation/heater/+/set/+` y a los asuntos interiores
  configurados;
- sin permiso para publicar órdenes si esa cuenta solo la usa el servicio.

Un PUBACK rechazado —por ejemplo por una ACL— se registra con asunto y motivo,
nunca con payload o credenciales. Credenciales rechazadas se reintentan cada
cinco minutos; un broker o túnel inalcanzable usa espera creciente de 1 a 120 s.
Al reconectar se publica disponibilidad, luego todo el descubrimiento y por
último el estado y las suscripciones.

### Disponibilidad y órdenes

La última voluntad marca todo como no disponible si muere el publicador o cae
el túnel. Si solo falta el latido del controlador, salida y potencia quedan no
disponibles, mientras configuración y salud siguen visibles. Nunca se convierte
«no sé» en salida apagada ni potencia cero.

Home Assistant puede modificar únicamente `enabled` y `target_charge`. Son
cambios de configuración; el planificador decide las salidas. Potencia máxima,
pin, nivel activo y cualquier campo futuro quedan fuera por lista blanca. Las
órdenes deben publicarse con QoS 1 y **sin retención**. Toda orden recibida con
`retain=true` se rechaza antes de leer su carga y se republica el valor realmente
almacenado.

### Temperatura interior y reserva

```bash
dtc config set indoor_topic ha/sensor/temperatura_salon/state --heater salon
dtc config set indoor_max_age_minutes 30
dtc config set indoor_min_plausible_c -20
dtc config set indoor_max_plausible_c 50
```

El instante utilizado es el de recepción local. Una carga vacía, no numérica o
implausible invalida inmediatamente la medida anterior; una medida demasiado
antigua se trata como ausente. En esos casos el controlador vuelve al cálculo
anterior basado en previsión y registra solo la entrada y salida de la reserva.
Una estancia en objetivo o por encima conserva `min_charge`, no cae a cero.
Eliminar el origen restaura exactamente el comportamiento anterior:

```bash
dtc config set indoor_topic '' --heater salon
```

Diagnóstico rápido:

| Síntoma | Revisión |
| --- | --- |
| no aparece ninguna entidad | integración MQTT y `DTC_MQTT_DISCOVERY_PREFIX` |
| todo no disponible | unidad MQTT, broker/túnel o base de datos |
| solo salida/potencia no disponibles | latido del controlador; es la respuesta honesta |
| una orden vuelve atrás | fue inválida, no permitida o retenida; mira el journal |
| conexión sin actualizaciones | PUBACK/ACL del asunto indicado en el journal |
| demanda sin temperatura real | asunto, antigüedad, rango plausible y registro de reserva |

La guía operativa completa está en
[`specs/004-home-assistant/quickstart.md`](specs/004-home-assistant/quickstart.md).

## API HTTP

Una API de lectura y configuración, servida como **servicio independiente** del
controlador. Los dos procesos se comunican solo a través de la base de datos: parar,
reiniciar o hacer fallar la API **no afecta a la calefacción**, y esa es la razón de que sean
dos y no uno.

La API **no acciona ninguna salida**. No hay forzado manual ni boost: solo el planificador
decide qué carga. Ninguna de sus rutas tiene acceso al medio de conmutar un relé, y un test lo
verifica.

### Puesta en marcha

```bash
python -m pip install -e '.[dev,api]'

export DTC_DATABASE_URL="sqlite:///$(pwd)/var/dtc.db"
export DTC_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

dtc db upgrade      # si vienes de la fase anterior; db init si empiezas de cero
dtc api             # escucha en 127.0.0.1:8420
```

```bash
curl -s -H "Authorization: Bearer $DTC_API_TOKEN" localhost:8420/api/v1/status | jq
open http://localhost:8420/docs      # también exige el token
```

### El token

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Va en `DTC_API_TOKEN`, en el fichero de entorno. Mínimo 32 caracteres: la API **se niega a
arrancar** con un token vacío, corto o igual al de ejemplo, para que no pueda quedarse
escuchando sin protección real. Rotarlo es editar el fichero y reiniciar la API.

**Trátalo como la contraseña del cuadro eléctrico, porque funcionalmente lo es**: quien lo
tenga puede cambiar la potencia máxima y la asignación de pines.

### Leer el estado, y por qué puede decir «no lo sé»

`GET /api/v1/status` devuelve la fotografía completa: acumuladores activos, potencia
instantánea, plan en curso, previsión con su origen y minutos no atendidos.

Lo primero que hay que leer de la respuesta es `controller.state_is_current`. Como la API y el
controlador son procesos distintos, la API deduce el estado de las salidas del histórico de
transiciones. Si el controlador está parado o colgado, ese histórico sigue ahí. Para no
mentir, el controlador publica un **latido** y la API distingue cuatro situaciones:

| `liveness` | Significa |
| --- | --- |
| `live` | el controlador responde y está sano |
| `live_degraded` | responde, pero no alcanza la base de datos o el proveedor meteorológico |
| `stale` | dejó de publicar: no se sabe qué está pasando |
| `never_seen` | nunca arrancó contra esta base de datos |

Con `state_is_current` a `false`:

- `power` es **`null`**. No se publica una potencia que nadie puede confirmar.
- `output_on` de cada acumulador es **`null`**, no `false`. Son cosas distintas: `false` dice
  «está apagado», `null` dice «no tengo prueba de nada». El último valor registrado sigue
  disponible en `last_known_output_on` con su `changed_at`.

Eso **no es un fallo**: es la API negándose a afirmar algo que no puede saber. Un panel que
diga que un acumulador de 2,8 kW está cargando cuando no lo está lleva a decisiones
equivocadas sobre la instalación eléctrica.

La respuesta avisa además con `multiple_controllers_suspected` si parece haber **más de un
controlador** contra la misma base de datos. Dos procesos conmutando los mismos relés es un
riesgo eléctrico; la API lo señala y no arbitra.

### Editar la configuración

Toda escritura exige la revisión que leíste. Es el bloqueo optimista que impide que dos
clientes se pisen.

```bash
TOKEN="Authorization: Bearer $DTC_API_TOKEN"
REV=$(curl -s -H "$TOKEN" localhost:8420/api/v1/config | jq .config_revision)

curl -s -X PATCH -H "$TOKEN" -H 'Content-Type: application/json' \
  -d "{\"revision\": $REV, \"field\": \"max_total_power_kw\", \"value\": \"5.2\"}" \
  localhost:8420/api/v1/config | jq
```

Reenviar una revisión vieja devuelve **409**: no es un error a evitar, es la protección
funcionando. Las mismas validaciones y los mismos rechazos que por consola.

### Histórico

```bash
curl -s -H "$TOKEN" \
  'localhost:8420/api/v1/history/plans?from=2026-01-01T00:00:00Z&limit=10' | jq
```

Siempre paginado: 50 por defecto, 500 como máximo. Ninguna consulta devuelve el histórico
completo.

### Despliegue en la Raspberry Pi

```bash
sudo ./scripts/install-service.sh --with-api      # añade --with-gpio si procede
sudoedit /etc/dynamic-thermal-charge/environment  # define DTC_API_TOKEN

sudo systemctl start dynamic-thermal-charge       # controlador
sudo systemctl start dynamic-thermal-charge-api   # API
```

Son dos servicios sin ninguna dependencia entre ellos. Merece la pena comprobarlo una vez:

```bash
sudo systemctl stop dynamic-thermal-charge-api    # el controlador sigue a lo suyo
```

La unidad de la API **no** pertenece al grupo `gpio`: no puede alcanzar el hardware ni
queriendo.

### Exponer la API en la red — leer antes de hacerlo

Por defecto escucha en `127.0.0.1`, accesible solo desde la propia Pi. Para llegar desde otro
equipo:

```bash
# En /etc/dynamic-thermal-charge/environment
DTC_API_HOST=0.0.0.0
```

**La API sirve en claro, sin cifrado.** Cualquiera con acceso a tu red puede leer el token al
pasar, y con el token puede cambiar la potencia máxima y los pines. En una red doméstica de
confianza es razonable. **Publicarla en internet no lo es** sin un proxy inverso con TLS
delante, y eso queda fuera del alcance de esta fase.

Para que un navegador la consuma desde otro origen hay que declararlo a propósito:

```bash
DTC_API_CORS_ORIGINS=http://panel.lan:4200
```

La lista está vacía por defecto. No se admite comodín.

### Diagnóstico

| Síntoma | Causa probable |
| --- | --- |
| la API no arranca y habla del token | `DTC_API_TOKEN` ausente, vacío, con menos de 32 caracteres o de ejemplo |
| **401** en todo | falta la cabecera `Authorization`, o el token no coincide |
| `liveness: never_seen` | el controlador nunca arrancó contra esta base de datos |
| `liveness: stale` | el controlador está parado o colgado; revisa su unidad |
| `state_is_current: false` y `power: null` | correcto por diseño: sin latido reciente no se afirma nada |
| `multiple_controllers_suspected: true` | hay más de un controlador vivo. Revísalo: es un riesgo eléctrico |
| **503** `schema_unusable` | ejecuta `dtc db upgrade`. La API nunca migra por sí misma |
| **503** `store_unavailable` | la base de datos no responde |
| **409** al escribir | otro cliente escribió primero; relee y reintenta |
| el navegador bloquea las peticiones | falta declarar su origen en `DTC_API_CORS_ORIGINS` |

## Panel web

Un panel de navegador para ver el estado, editar la configuración y consultar el histórico.
Consume solo la API y **no puede accionar ninguna salida**: la API no ofrece esa operación.

### Se compila fuera del dispositivo

**En la Raspberry Pi no se instala Node, y no hace falta.** Un `npm install` en un Cortex-A7 con
1 GB no termina, y las dependencias del panel son 253 MB frente a los ~260 kB que se copian al
dispositivo. La constitución del proyecto lo prohíbe explícitamente, y el instalador no instala
ninguna herramienta de construcción.

Requisitos en tu máquina: **Node ≥ 22.22.3**, o ≥ 24.15, o ≥ 26.

```bash
node --version
cd frontend && npm install
```

### Desarrollo local

Necesitas la API en marcha:

```bash
# Terminal 1
export DTC_DATABASE_URL="sqlite:///$(pwd)/var/dtc.db"
export DTC_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
dtc db upgrade && dtc api

# Terminal 2
cd frontend && npm start        # http://localhost:4200
```

El servidor de desarrollo hace de intermediario hacia la API igual que nginx en el dispositivo,
así que tampoco aquí hacen falta orígenes cruzados. El panel pide la credencial al abrirlo: es el
valor de `DTC_API_TOKEN`.

```bash
cd frontend && npm test         # sin red, sin API real, sin navegador
cd frontend && npm run build    # falla si el paquete supera el presupuesto
```

### Lo que el panel se niega a afirmar

Lo primero que se lee en la pantalla de estado es si el controlador está visible. Como la API y el
controlador son procesos distintos, la API deduce el estado de las salidas del histórico de
transiciones, y si el controlador está parado ese histórico sigue ahí.

Cuando el estado **no es vigente**, el panel:

- **no muestra ninguna cifra de potencia**, ni un cero: un cero afirmaría que no se consume nada;
- pinta cada acumulador como **«sin confirmar»**, con el último valor conocido etiquetado como
  pasado y el instante en que cambió;
- avisa desde cuándo no se ve al controlador.

Eso **no es un fallo**. Es el panel negándose a afirmar algo que no puede saber. Un panel que diga
que un acumulador de 2,8 kW está cargando cuando no lo está lleva a decisiones equivocadas sobre
la instalación eléctrica.

Los tres estados —cargando, en reposo y sin confirmar— se distinguen por texto y forma, no solo
por color.

Si el panel avisa de que **parece haber más de un controlador**, revísalo: dos procesos
conmutando los mismos relés es un riesgo eléctrico.

### Editar la configuración

Cada escritura envía la revisión que se leyó. Si otra pestaña escribió antes, el panel avisa de
que la configuración cambió y ofrece releer, sin sobrescribir. No es un error a evitar: es la
protección funcionando.

Tres campos piden confirmación explícita, y solo esos tres, porque su error se paga en el cuadro
eléctrico: **potencia máxima simultánea, pin BCM y nivel activo**. El resto se cambia sin
ceremonia; pedir confirmación para todo enseña a confirmar sin leer.

### Desplegar en la Raspberry Pi

```bash
# 1. Compilar AQUÍ, nunca allí
cd frontend && npm run build

# 2. Copiar los ficheros
rsync -a --delete dist/panel/browser/ pi:/tmp/panel/
ssh pi 'sudo rsync -a --delete /tmp/panel/ /var/www/dynamic-thermal-charge/'

# 3. Solo la primera vez: instalar el servicio y el sitio de nginx
sudo ./scripts/install-service.sh --with-api --with-panel
ssh pi 'sudo apt-get install -y nginx'
ssh pi 'sudo ln -sf /etc/nginx/sites-available/dynamic-thermal-charge /etc/nginx/sites-enabled/ \
        && sudo rm -f /etc/nginx/sites-enabled/default \
        && sudo nginx -t && sudo systemctl reload nginx'
```

El panel queda en `http://<la-pi>/`. El instalador **no** habilita nginx ni arranca nada: imprime
lo que hay que ejecutar.

nginx sirve los ficheros y hace de intermediario hacia la API, así que el navegador ve un único
origen. Consecuencia importante: **la API sigue escuchando solo en `127.0.0.1` y nunca necesita
exponerse**. nginx es el único componente accesible desde la red.

Comprobarlo merece la pena una vez:

```bash
ssh pi 'ss -tlnp | grep 8420'          # debe decir 127.0.0.1:8420, no 0.0.0.0
curl -s http://<la-pi>:8420/health     # debe fallar: la API no escucha ahí fuera
curl -s http://<la-pi>/health          # debe responder: nginx sí
```

### Actualizar el panel

```bash
cd frontend && npm run build
rsync -a --delete dist/panel/browser/ pi:/tmp/panel/
ssh pi 'sudo rsync -a --delete /tmp/panel/ /var/www/dynamic-thermal-charge/'
```

**No hay que recargar nginx ni borrar la caché del navegador.** Los recursos llevan una huella en
el nombre y `index.html` se sirve sin cachear. Si alguna vez ves la interfaz antigua tras
actualizar, lo primero que hay que revisar es que `index.html` no esté siendo cacheado.

### Añadir cifrado en tránsito

**Sin cifrado, el panel y la API sirven en claro.** Cualquiera con acceso a tu red puede leer la
credencial al pasar, y quien la tenga puede cambiar la potencia máxima y la asignación de pines.
En una red doméstica de confianza es razonable. **Publicarlo en internet no lo es.**

`deploy/nginx/dynamic-thermal-charge.conf` lleva el bloque preparado y **comentado**. Activarlo
requiere un certificado y su clave, descomentar el bloque y recargar nginx. No se activa por
defecto porque implica gestionar certificados, y esa decisión es del operador.

### Diagnóstico del panel

| Síntoma | Causa probable |
| --- | --- |
| pide la credencial una y otra vez | el token no coincide con `DTC_API_TOKEN`, o se rotó en el servidor |
| **404** al recargar una ruta interna | falta `try_files … /index.html` en la configuración de nginx |
| tras actualizar sigue la interfaz antigua | `index.html` se está cacheando; debe ir con `no-cache` |
| **502** desde nginx | la API no está en marcha: `systemctl status dynamic-thermal-charge-api` |
| todo da **401** por nginx pero funciona en local | nginx no propaga la cabecera de autorización |
| «estado no actual» de forma permanente | el controlador está parado o colgado: `systemctl status dynamic-thermal-charge` |
| no se muestra potencia | correcto por diseño: sin latido reciente no se publica una cifra que nadie puede confirmar |
| avisa de más de un controlador | revísalo: dos procesos sobre los mismos relés es un riesgo eléctrico |
| dice que el esquema necesita atención | ejecuta `dtc db upgrade` **en el dispositivo**; el panel no puede |
| no refresca con la pestaña de fondo | correcto por diseño: se detiene para no cargar la Pi y se reanuda al volver |

## GPIO real

El driver real usa [GPIO Zero](https://gpiozero.readthedocs.io/en/stable/)
con el backend `lgpio`. Se instala únicamente mediante una opción explícita:

```bash
sudo ./scripts/install-service.sh --with-gpio
```

Esta opción instala `swig` y `liblgpio-dev`, añade las dependencias Python del
extra `gpio` y concede al usuario del servicio pertenencia al grupo `gpio`. La
unidad permanece en modo simulado.

### Prueba previa con LEDs

Esta prueba debe superarse antes de conectar una placa de relés, contactores o
acumuladores. Durante todo el ensayo deben permanecer desconectados tanto la
red de 230 V como el circuito de potencia. Los GPIO trabajan a 3,3 V: nunca se
debe aplicar 5 V a un GPIO ni conectar un LED sin resistencia en serie.

Material necesario:

- Raspberry Pi 2B apagada y desconectada mientras se modifica el cableado.
- Placa de pruebas y cables de conexión.
- Cuatro LEDs, uno por salida.
- Cuatro resistencias de 1 kΩ, una por LED. También son adecuados valores entre
  470 Ω y 1 kΩ para esta prueba.
- Multímetro, recomendado para comprobar tensiones y continuidad.

La aplicación usa numeración **BCM**, que no coincide con la posición física
del conector. La configuración de ejemplo corresponde a este mapa:

| Acumulador | GPIO BCM | Pin físico |
| --- | ---: | ---: |
| Salón | 17 | 11 |
| Entrada | 18 | 12 |
| Habitaciones | 22 | 15 |
| Buhardilla | 23 | 16 |
| Alimentación 3,3 V | — | 1 |
| GND, solo si se necesita medir | — | 6 |

Hay que verificar la orientación del conector de 40 pines antes de cablear; no
se debe deducir la posición observando únicamente la fila o contando desde un
extremo sin identificar primero los pines 1 y 2.

#### Por qué el LED se conecta a 3,3 V

En la instalación sembrada, las cuatro salidas tienen `active_high` a `false`. Son, por tanto, activas a nivel bajo:

- Estado lógico OFF: el GPIO presenta nivel alto.
- Estado lógico ON: el GPIO presenta nivel bajo y absorbe corriente.

Para que el LED represente el estado lógico de la salida, cada canal se cablea
así:

```text
3,3 V (pin físico 1)
  │
  ├── resistencia 1 kΩ ── ánodo LED ── cátodo LED ── GPIO objetivo
  │                         pata larga    pata corta / lado plano
```

No se debe usar el montaje convencional `GPIO → LED → GND` manteniendo
`active_high: false`, porque mostraría el estado contrario al esperado. Si el
módulo de relés definitivo es activo a nivel alto habrá que cambiar tanto el
cableado de prueba como `active_high`, de forma deliberada y conjunta.

#### 1. Preparar el sistema

Instalar el servicio y las dependencias GPIO, pero no arrancar todavía el
controlador persistente:

```bash
sudo ./scripts/install-service.sh --with-gpio
sudo systemctl disable --now dynamic-thermal-charge
```

Comprobar que el usuario del servicio pertenece al grupo `gpio` y que existe
el dispositivo del controlador:

```bash
id dynamic-thermal-charge
ls -l /dev/gpiochip0
```

La salida de `id` debe incluir `gpio`. También se debe ejecutar
`dtc config show` y confirmar que los números BCM y los valores de `active_high`
coinciden con el montaje previsto.

#### 2. Cablear un único canal

1. Apagar la Raspberry y desconectar su alimentación.
2. Confirmar que no hay red, relés, contactores ni acumuladores conectados.
3. Montar solamente el LED de Salón entre 3,3 V y BCM 17 (pin físico 11), con
   su resistencia de 1 kΩ y respetando la polaridad.
4. Revisar visualmente que no haya puentes entre 3,3 V, GND y pines contiguos.
5. Encender la Raspberry. El LED debe permanecer apagado en reposo.

Si este primer canal funciona, apagar de nuevo la Raspberry y añadir los otros
tres LEDs siguiendo la tabla. Nunca cambiar conexiones con la placa encendida.

#### 3. Ejecutar el autotest

El servicio debe seguir detenido. Ejecutar el test como el mismo usuario que
usará el controlador:

```bash
sudo -u dynamic-thermal-charge \
  /opt/dynamic-thermal-charge/venv/bin/dynamic-thermal-charge \
  gpio-self-test \
  --driver gpio \
  --confirm-hardware-test \
  --test-seconds 1
```

La confirmación explícita evita iniciar el test por accidente. El programa
fuerza primero todos los canales a OFF y después enciende durante un segundo,
en este orden:

1. Salón, BCM 17.
2. Entrada, BCM 18.
3. Habitaciones, BCM 22.
4. Buhardilla, BCM 23.

Solo debe iluminarse un LED cada vez. Al finalizar, todos deben quedar
apagados. El orden observado debe coincidir también con los mensajes del log.

#### 4. Probar una interrupción

El apagado seguro también debe verificarse cuando el proceso se interrumpe.
Repetir el test con un intervalo largo y pulsar `Ctrl+C` mientras haya un LED
encendido:

```bash
sudo -u dynamic-thermal-charge \
  /opt/dynamic-thermal-charge/venv/bin/dynamic-thermal-charge \
  gpio-self-test \
  --driver gpio \
  --confirm-hardware-test \
  --test-seconds 10
```

El LED activo debe apagarse inmediatamente, todos los demás deben continuar
apagados y ninguno debe volver a encenderse. Los logs deben indicar la parada
controlada y el cierre del driver.

#### Criterios para dar la prueba por válida

- Todos los LEDs permanecen apagados durante el arranque, antes del test, al
  terminar y después de `Ctrl+C`.
- Se encienden en el orden y en el GPIO indicados, solo uno cada vez.
- No hay destellos, iluminación tenue ni canales permanentemente activos.
- La secuencia física coincide con los nombres y estados registrados en el
  log.

Si cualquiera de estos puntos falla, no se debe conectar aún la placa de
relés. Hay que revisar la polaridad de los LEDs, las resistencias, la diferencia
entre numeración BCM y física, el valor `active_high` y el estado eléctrico del
pin durante el arranque.

Problemas habituales:

| Síntoma | Comprobación |
| --- | --- |
| `GPIO driver requires a Raspberry Pi` | El comando no se está ejecutando en la Raspberry. |
| No se puede abrir `/dev/gpiochip0` | Revisar `lgpio`, permisos del dispositivo y pertenencia al grupo `gpio`. |
| El LED no enciende | Revisar polaridad, continuidad, resistencia, pin físico y `active_high`. |
| El LED funciona al revés o queda encendido | El cableado y el nivel activo configurado no coinciden. |
| Se activa otro canal | Se ha confundido la numeración BCM con la numeración física. |
| Hay un destello durante el arranque | El estado seguro no está garantizado por hardware; añadir el pull-up o pull-down apropiado antes de continuar. |

### Paso posterior: placa de relés y systemd

Solo después de superar todas las pruebas con LEDs se pueden probar las
entradas aisladas de la placa de relés, todavía sin red de 230 V, contactores ni
acumuladores. Una entrada activa a nivel bajo necesita un pull-up físico
adecuado para conservar el estado inactivo durante el arranque, reinicio o
cuando ningún proceso controla el pin.

Tras verificar de nuevo cada canal, habilitar el driver GPIO en systemd:

```bash
sudo install -d /etc/systemd/system/dynamic-thermal-charge.service.d
sudo install -m 0644 \
  /etc/dynamic-thermal-charge/gpio-systemd-override.conf.example \
  /etc/systemd/system/dynamic-thermal-charge.service.d/gpio.conf
sudo systemctl daemon-reload
sudo systemctl restart dynamic-thermal-charge
```

Después del arranque, comprobar el estado y seguir los logs:

```bash
systemctl status dynamic-thermal-charge
journalctl -u dynamic-thermal-charge -f
```

El relé debe tener aislamiento y alimentación adecuados. Los contactores deben
usar contactos normalmente abiertos, estar dimensionados para la carga y ser
instalados por un electricista. Nunca se debe conectar un acumulador, la red de
230 V ni una bobina de potencia directamente a un GPIO.

La ventana de carga puede definirse mediante horarios:

```bash
dtc config set timezone Europe/Madrid
dtc config set start_time 00:00
dtc config set end_time 08:00
dtc config set weekdays 0,1,2,3,4,5,6   # lunes=0, ascendente y sin repetidos
```

Cuando no se proporciona `--start`, la CLI selecciona el siguiente inicio
permitido. La duración se obtiene de `start_time` y `end_time`, incluyendo las
ventanas que atraviesan medianoche.

El nivel de log se configura globalmente:

```bash
dtc config set log_level INFO   # DEBUG, INFO, WARNING, ERROR o CRITICAL
```

Puede sobrescribirse para una ejecución concreta sin cambiar la configuración:

```bash
dtc run --log-level DEBUG
```

Los logs se escriben en la salida de error y el plan legible permanece en la
salida estándar, lo que permite redirigirlos de forma independiente.
Si el plan no puede cubrir toda la carga solicitada, se genera además un log
`WARNING` con los minutos pendientes de cada acumulador.

Los intervalos siempre se alinean con el reloj. Por ejemplo, una planificación
de 30 minutos iniciada a las 22:17 comenzará a las 22:30 y continuará a las
23:00, 23:30, etc. Para conservar límites naturales, `slot_minutes` debe ser un
divisor de 60 (por ejemplo, 15, 20, 30 o 60).

`dtc config show` sigue siendo la forma de comprobar el mapa de pines antes de
tocar hardware. Las ejecuciones en modo `simulated` no accionan ningún pin. El modo `gpio` usa
numeración BCM y mantiene las librerías específicas de Raspberry aisladas del
núcleo de planificación. La configuración de ejemplo debe adaptarse al nivel
activo y a las características eléctricas del módulo de relés definitivo.

## Decisiones de diseño

- Dependencias mínimas para los recursos de una Raspberry Pi 2B: el núcleo de
  planificación no tiene dependencias de runtime, y la persistencia vive en un
  extra opcional.
- Cálculos enteros en vatios y minutos para evitar errores de coma flotante.
- Planificador determinista y comprobable mediante tests.
- Las peticiones no atendidas se muestran explícitamente; nunca se oculta una
  sobrecarga o una ventana de carga insuficiente.
