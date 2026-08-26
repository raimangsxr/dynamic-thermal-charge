# Quickstart — Configuración en base de datos

**Feature**: `001-config-database`

Todos los comandos admiten indistintamente `dynamic-thermal-charge` o su alias corto
`dtc`. Los ejemplos de esta guía usan el nombre largo; los de `contracts/cli.md`, el corto.

## Desarrollo local con SQLite

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,db]'

export DTC_DATABASE_URL="sqlite:///$(pwd)/var/dtc.db"
dynamic-thermal-charge db init        # crea esquema y siembra la instalación de ejemplo
dynamic-thermal-charge config show    # revisa qué se ha sembrado
dynamic-thermal-charge run            # planifica
pytest
```

`db init` es idempotente: se puede repetir sin miedo. No sobrescribe una configuración
existente.

## Ajustar la instalación

```bash
# Parámetros de la instalación
dynamic-thermal-charge config set max_total_power_kw 6.0
dynamic-thermal-charge config set slot_minutes 30
dynamic-thermal-charge config set start_time 00:00
dynamic-thermal-charge config set end_time 08:00
dynamic-thermal-charge config set retention_days 365

# Parámetros de un acumulador
dynamic-thermal-charge config set target_charge 0.8 --heater salon
dynamic-thermal-charge config set enabled false --heater buhardilla

# Alta y baja
dynamic-thermal-charge config add-heater cocina \
  --power-kw 1.2 --full-charge-hours 7 \
  --output gpio --pin 24 --no-active-high \
  --target-temperature-c 20 --design-outdoor-temperature-c -2

dynamic-thermal-charge config remove-heater cocina --yes
```

Cada cambio se valida contra la configuración completa resultante. Un cambio que dejaría la
instalación inválida no se aplica y el error dice qué campo lo impide:

```bash
$ dynamic-thermal-charge config set slot_minutes 45
error: slot_minutes debe ser divisor de 60; recibido 45

$ dynamic-thermal-charge config set pin 17 --heater entrada
error: pin 17 ya está asignado al acumulador «salon»
```

## PostgreSQL remoto

```bash
export DTC_DATABASE_URL="postgresql+pg8000://dtc:CLAVE@servidor:5432/dtc"
dynamic-thermal-charge db init
dynamic-thermal-charge config show
```

El driver es `pg8000`, Python puro: se instala en la Raspberry Pi sin compilador y sin
`libpq`. No se admite `psycopg2` (ver `research.md`, D2).

El comportamiento debe ser idéntico al de SQLite. Si observas una diferencia de plan entre
ambos motores con la misma configuración, es un bug.

## Despliegue en la Raspberry Pi

```bash
sudo ./scripts/install-service.sh          # o --with-gpio para hardware real
sudoedit /etc/dynamic-thermal-charge/environment   # define DTC_DATABASE_URL y AEMET_API_KEY
sudo -u dynamic-thermal-charge \
  /opt/dynamic-thermal-charge/venv/bin/dynamic-thermal-charge db init
sudo -u dynamic-thermal-charge \
  /opt/dynamic-thermal-charge/venv/bin/dynamic-thermal-charge config show
sudo systemctl start dynamic-thermal-charge
```

Por defecto, la base de datos local vive en
`/var/lib/dynamic-thermal-charge/dynamic-thermal-charge.db`, propiedad del usuario del
servicio.

## Actualizar desde una versión con YAML — leer antes de actualizar

**La configuración no se migra automáticamente.** No existe importador de YAML: fue una
decisión deliberada de esta fase. Después de actualizar hay que reintroducir a mano la
instalación real.

Procedimiento recomendado:

1. **Antes** de actualizar, guarda una copia del YAML vigente:
   ```bash
   sudo cp /etc/dynamic-thermal-charge/config.yaml ~/config.yaml.bak
   ```
2. Detén el servicio: `sudo systemctl stop dynamic-thermal-charge`.
3. Actualiza e inicializa la base de datos (`db init`).
4. Con la copia delante, reproduce la configuración con `config set`, `config add-heater` y
   `config remove-heater`. Presta especial atención a **los pines BCM, `active_high` y la
   potencia máxima**: un error aquí se paga en el cuadro eléctrico.
5. Verifica con `config show` **campo por campo** contra la copia.
6. Antes de arrancar con hardware real, repite el autotest de LEDs del README.

El servicio no arranca con una configuración inválida y no activa ninguna salida mientras no
tenga una configuración válida, así que un olvido se manifiesta como servicio parado, nunca
como un relé cerrado por error.

## Diagnóstico

| Síntoma | Causa probable |
| --- | --- |
| `DTC_DATABASE_URL no está definida` | falta la variable en `/etc/dynamic-thermal-charge/environment` |
| `motor no admitido` | la URL no empieza por `sqlite:` ni `postgresql+pg8000:` |
| `base de datos no inicializada` | falta ejecutar `db init` |
| `migración pendiente` | ejecuta `db upgrade` |
| `revisión de esquema desconocida` | la base de datos la migró un binario más nuevo. Actualiza el servicio; no se arranca sobre un esquema que no comprende |
| `no hay configuración` | la base de datos está inicializada pero vacía; ejecuta `db init` para sembrar |
| el servicio queda degradado con PostgreSQL | pérdida de red. Conserva el plan en curso y reintenta; revisa los logs de transición |
