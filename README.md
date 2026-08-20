# Dynamic Thermal Charge

Planificador configurable de carga para acumuladores eléctricos, pensado para
funcionar en una Raspberry Pi 2B sin acoplar la lógica de negocio al hardware.

El proyecto se encuentra en una primera fase funcional: carga una instalación
desde YAML y calcula un plan por intervalos respetando el límite de potencia.
Incluye un driver simulado como frontera de salida. La previsión meteorológica,
el modelo térmico y el GPIO real se añadirán como componentes independientes.

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
