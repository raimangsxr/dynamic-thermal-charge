# Dynamic Thermal Charge

Planificador configurable de carga para acumuladores eléctricos, pensado para
funcionar en una Raspberry Pi 2B sin acoplar la lógica de negocio al hardware.

El proyecto se encuentra en una primera fase funcional: carga una instalación
desde YAML, calcula la demanda mediante un modelo térmico y crea un plan por
intervalos respetando el límite de potencia. Incluye meteorología y salidas
simuladas; los proveedores meteorológicos externos y el GPIO real se añadirán
como componentes independientes.

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

Por seguridad, `--run-controller` utiliza exclusivamente
`SimulatedOutputDriver`, aunque el YAML declare salidas GPIO. El soporte GPIO
real todavía no está habilitado.

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

Las salidas declaradas como `simulated` no accionan ningún pin. El futuro
driver GPIO usará numeración BCM y mantendrá las librerías de Raspberry fuera
del núcleo.

La configuración GPIO de ejemplo usa BCM 17, 18, 22 y 23 con salidas activas a
nivel bajo. Es imprescindible adaptarla al módulo de relés concreto. Los GPIO
solo pueden controlar entradas aisladas de relés o contactores correctamente
dimensionados; nunca deben alimentar ni conmutar directamente un acumulador.
Esta versión valida la configuración, pero todavía no acciona GPIO reales.

## Decisiones de diseño

- Dependencias mínimas para los recursos de una Raspberry Pi 2B.
- Cálculos enteros en vatios y minutos para evitar errores de coma flotante.
- Planificador determinista y comprobable mediante tests.
- Las peticiones no atendidas se muestran explícitamente; nunca se oculta una
  sobrecarga o una ventana de carga insuficiente.
