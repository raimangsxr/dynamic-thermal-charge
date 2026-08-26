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
