# Dynamic Thermal Charge

Planificador configurable de carga para acumuladores eléctricos, pensado para
funcionar en una Raspberry Pi 2B sin acoplar la lógica de negocio al hardware.

El proyecto carga una instalación desde YAML, obtiene la predicción
meteorológica, calcula la demanda mediante un modelo térmico y crea un plan por
intervalos respetando el límite de potencia. Incluye un controlador persistente
con salidas simuladas y un driver GPIO real aislado del núcleo de planificación.

## Requisitos

- Python 3.12 o superior
- PyYAML 6

## Puesta en marcha

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
dynamic-thermal-charge examples/home.yaml
pytest
```

También puede ejecutarse sin instalar el comando:

```bash
PYTHONPATH=src python -m dynamic_thermal_charge examples/home.yaml
```

## Configuración

`examples/home.yaml` representa una simulación. `examples/raspberry-pi.yaml`
añade una ventana nocturna y asignaciones GPIO para un despliegue en Raspberry
Pi 2B. Ninguna de las dos configuraciones limita el número de acumuladores.

- `max_total_power_kw`: potencia máxima simultánea dedicada a acumuladores.
- `slot_minutes`: resolución del plan.
- `window_hours`: duración de la ventana de carga.
- `full_charge_hours`: tiempo requerido por el aparato para una carga completa.
- `target_charge`: fracción de carga solicitada para esta simulación (`0..1`).
- `priority`: los valores mayores se atienden primero cuando falta capacidad.

En la configuración de despliegue, un perfil térmico sustituye el porcentaje
manual:

```yaml
weather:
  provider: simulated
  simulated:
    average_temperature_c: 8.0
    minimum_temperature_c: 3.0

heaters:
  - id: salon
    # ...
    thermal:
      target_temperature_c: 21.0
      design_outdoor_temperature_c: -2.0
      thermal_factor: 1.0
      min_charge: 0.10
      max_charge: 1.0
```

El motor calcula una fracción lineal entre la temperatura exterior media de
diseño (carga completa) y la temperatura objetivo (sin carga), aplica el factor
térmico de la estancia y respeta los límites configurados.

### AEMET OpenData

La configuración de Raspberry usa la predicción diaria de AEMET por municipio:

```yaml
weather:
  provider: aemet
  aemet:
    municipality_code: "28079"
    api_key_env: AEMET_API_KEY
    timeout_seconds: 10
  fallback:
    average_temperature_c: 8.0
    minimum_temperature_c: 3.0
```

`28079` es únicamente el ejemplo de Madrid; debe sustituirse por el código INE
de cinco dígitos de la vivienda. La API key nunca se guarda en YAML:

```bash
export AEMET_API_KEY='clave-obtenida-en-AEMET-OpenData'
dynamic-thermal-charge examples/raspberry-pi.yaml
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
dynamic-thermal-charge examples/raspberry-pi.yaml --watch-weather
```

Sus intervalos se configuran en minutos:

```yaml
weather:
  # proveedor, credenciales y fallback...
  watchdog:
    retry_minutes: 15
    refresh_minutes: 180
```

Si AEMET falla, el primer plan se crea inmediatamente con el fallback y el
proceso reintenta el proveedor primario cada `retry_minutes`. Cuando AEMET se
recupera, registra la recuperación y recalcula el plan con la predicción real.
Mientras el proveedor funciona, renueva la previsión y el plan cada
`refresh_minutes`. `Ctrl+C` detiene el watchdog de forma limpia.

### Controlador persistente

El controlador ejecuta el plan activo contra el driver simulado:

```bash
dynamic-thermal-charge examples/raspberry-pi.yaml --run-controller
```

Su estado se configura de forma independiente:

```yaml
runtime:
  state_file: ../var/active-plan.json
  poll_seconds: 5
```

El servicio fuerza todas las salidas a OFF al arrancar, guarda cada plan nuevo
de forma atómica y recupera el último plan válido tras un reinicio. Comprueba el
slot activo cada `poll_seconds` y solo genera acciones cuando cambia el estado.
Ante un fallo de actualización conserva el último plan persistido; si no hay
ninguno válido mantiene todas las salidas apagadas. Al recibir `Ctrl+C` o una
excepción fuerza de nuevo todas las salidas a OFF.

Sin indicar nada más, `--run-controller` utiliza `SimulatedOutputDriver`,
aunque el YAML declare salidas GPIO. El hardware real solo se habilita de
forma explícita con `--driver gpio`.

## Instalación como servicio systemd

En Raspberry Pi OS con Python 3.12, ejecutar desde el repositorio:

```bash
sudo ./scripts/install-service.sh
```

El instalador crea un usuario sin shell, un entorno virtual aislado y estas
rutas:

- `/opt/dynamic-thermal-charge/venv`: aplicación instalada.
- `/etc/dynamic-thermal-charge/config.yaml`: configuración, conservada en las
  actualizaciones posteriores.
- `/etc/dynamic-thermal-charge/environment`: API key, modo `0600` y también
  conservada en actualizaciones.
- `/var/lib/dynamic-thermal-charge/active-plan.json`: último plan válido.

Antes de iniciar, configurar el secreto y revisar el código municipal, límites
de potencia y horarios:

```bash
sudoedit /etc/dynamic-thermal-charge/environment
sudoedit /etc/dynamic-thermal-charge/config.yaml
sudo systemctl start dynamic-thermal-charge
sudo systemctl enable dynamic-thermal-charge
```

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

En `examples/raspberry-pi.yaml`, las cuatro salidas tienen
`active_high: false`. Son, por tanto, activas a nivel bajo:

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

La salida de `id` debe incluir `gpio`. También se debe revisar
`/etc/dynamic-thermal-charge/config.yaml` y confirmar que los números BCM y los
valores de `active_high` coinciden con el montaje previsto.

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
  /etc/dynamic-thermal-charge/config.yaml \
  --gpio-self-test \
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
  /etc/dynamic-thermal-charge/config.yaml \
  --gpio-self-test \
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

Una configuración de despliegue puede definir la ventana mediante horarios:

```yaml
schedule:
  timezone: Europe/Madrid
  start_time: "00:00"
  end_time: "08:00"
  weekdays: [monday, tuesday, wednesday, thursday, friday, saturday, sunday]
```

Cuando no se proporciona `--start`, la CLI selecciona el siguiente inicio
permitido. La duración se obtiene de `start_time` y `end_time`, incluyendo las
ventanas que atraviesan medianoche.

El nivel de log se configura globalmente en el YAML:

```yaml
logging:
  level: INFO  # DEBUG, INFO, WARNING, ERROR o CRITICAL
```

Puede sobrescribirse para una ejecución concreta sin editar el fichero:

```bash
dynamic-thermal-charge examples/home.yaml --log-level DEBUG
```

Los logs se escriben en la salida de error y el plan legible permanece en la
salida estándar, lo que permite redirigirlos de forma independiente.
Si el plan no puede cubrir toda la carga solicitada, se genera además un log
`WARNING` con los minutos pendientes de cada acumulador.

Los intervalos siempre se alinean con el reloj. Por ejemplo, una planificación
de 30 minutos iniciada a las 22:17 comenzará a las 22:30 y continuará a las
23:00, 23:30, etc. Para conservar límites naturales, `slot_minutes` debe ser un
divisor de 60 (por ejemplo, 15, 20, 30 o 60).

Las ejecuciones en modo `simulated` no accionan ningún pin. El modo `gpio` usa
numeración BCM y mantiene las librerías específicas de Raspberry aisladas del
núcleo de planificación. La configuración de ejemplo debe adaptarse al nivel
activo y a las características eléctricas del módulo de relés definitivo.

## Decisiones de diseño

- Dependencias mínimas para los recursos de una Raspberry Pi 2B.
- Cálculos enteros en vatios y minutos para evitar errores de coma flotante.
- Planificador determinista y comprobable mediante tests.
- Las peticiones no atendidas se muestran explícitamente; nunca se oculta una
  sobrecarga o una ventana de carga insuficiente.
