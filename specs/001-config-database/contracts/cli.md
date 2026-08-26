# Contract — Interfaz de línea de comandos

**Feature**: `001-config-database`

Esta feature no expone interfaces de red (FR-015). Su único contrato externo es la CLI.

## Variable de entorno

| Variable | Obligatoria | Descripción |
| --- | :---: | --- |
| `DTC_DATABASE_URL` | sí | Ubicación de la base de datos. `sqlite:////ruta/absoluta.db` o `postgresql+pg8000://usuario:clave@host:puerto/base`. Servida por `/etc/dynamic-thermal-charge/environment`, modo `0600` |
| `AEMET_API_KEY` | según config | Sin cambios. El nombre de la variable se sigue declarando en la configuración |

Motores admitidos: `sqlite` y `postgresql`. Cualquier otro se rechaza al arrancar enumerando
los admitidos. La URL **nunca** se registra en los logs (D11).

## Cambio incompatible respecto a la CLI actual

El argumento posicional `config` (ruta del YAML) **desaparece** de todos los comandos. Con
él desaparecen la lectura de ficheros de configuración y su validación.

```text
antes:  dynamic-thermal-charge examples/home.yaml --run-controller
ahora:  dynamic-thermal-charge run --controller
```

Invocar el comando con un argumento posicional que parezca una ruta produce un error que
explica el cambio y remite a `dtc db init`, en lugar de un error genérico de argumentos.

## Comandos

`dtc` es un **alias real** del ejecutable, declarado en `[project.scripts]` junto a
`dynamic-thermal-charge`. Ambos nombres apuntan al mismo punto de entrada y son
intercambiables; los ejemplos usan el corto porque `dtc config set … --heater …` se
teclea a menudo. No es una abreviatura de documentación.

### `dtc db init`

Crea el esquema, aplica migraciones pendientes y siembra la instalación de ejemplo si no
existe ninguna configuración. Idempotente (FR-011, FR-012, FR-013).

Salida: qué se ha creado, qué se ha migrado y qué se ha omitido, más la revisión de esquema
resultante.

Códigos de salida: `0` correcto · `1` base de datos inalcanzable o URL inválida · `2`
revisión de esquema posterior a la que el servicio comprende.

### `dtc db upgrade`

Aplica únicamente migraciones pendientes. No siembra. Mismos códigos de salida.

### `dtc config show [--heater <id>]`

Solo lectura (FR-014). Muestra la configuración vigente completa, la revisión de
configuración y la revisión de esquema. No revela credenciales ni la cadena de conexión.

Con `--heater <id>` limita la salida a ese acumulador.

Códigos: `0` · `1` base de datos inalcanzable · `3` no hay configuración (sugiere
`dtc db init`) · `4` acumulador inexistente, enumerando los existentes.

### `dtc config set <campo> <valor> [--heater <id>]`

Modifica un campo (FR-032). Sin `--heater`, `<campo>` es de la instalación; con `--heater`,
del acumulador indicado.

Comportamiento exigido:

- Valida la **configuración completa resultante** antes de aplicar (FR-034). Un resultado
  inválido no cambia nada.
- Atómico y durable (FR-035).
- Informa del campo, su valor anterior y el nuevo (FR-036).
- Campo inexistente: error enumerando los campos admitidos (FR-037).
- Detecta la edición concurrente por revisión (FR-040).
- Rechaza valores con aspecto de credencial o de cadena de conexión (FR-038).
- No altera el plan en curso (FR-039).

Códigos: `0` · `1` base de datos inalcanzable · `4` campo o acumulador inexistente · `5`
la configuración resultante sería inválida · `6` conflicto de edición concurrente · `7`
valor rechazado por parecer un secreto.

### `dtc config add-heater <id> --power-kw <v> --full-charge-hours <v> [opciones]`

Añade un acumulador (FR-033). Opciones para nombre, modelo, prioridad, carga objetivo,
habilitación, tipo de salida, pin, nivel activo y campos del perfil térmico.

Códigos: `0` · `1` · `5` configuración resultante inválida, incluido pin ya en uso · `8`
el identificador ya existe.

### `dtc config remove-heater <id>`

Elimina un acumulador con su salida y su perfil térmico. **Conserva su histórico**
(FR-033). Exige confirmación explícita salvo `--yes`.

Códigos: `0` · `1` · `4` no existe.

### `dtc history prune`

Aplica la política de retención y comunica cuántos registros ha eliminado (FR-022). Nunca
toca la configuración ni el plan activo (FR-023). Con retención ilimitada no elimina nada.

### `dtc run [--controller | --watch-weather] [--driver simulated|gpio] [--start <iso>] [--log-level <nivel>]`

Sustituye a la invocación actual. Semántica de planificación, watchdog, controlador y
selección de driver **sin cambios**, salvo que la configuración se lee de la base de datos.
`--driver gpio` sigue siendo la única forma de habilitar hardware real.

Códigos: `0` · `1` base de datos inalcanzable en el arranque · `2` revisión de esquema
desconocida · `3` sin configuración · `5` configuración almacenada inválida.

En todos los casos de error, **ninguna salida se activa** (FR-024, Principio I).

### `dtc gpio-self-test`

Sin cambios funcionales. Conserva `--confirm-hardware-test` y `--test-seconds`, y ahora lee
los pines de la base de datos.

## Contrato de errores

Todo error de configuración identifica el campo ofensor y, cuando aplica, el acumulador
(FR-008). Se emite a la salida de error; la salida estándar queda para el plan legible, como
hoy.

| Situación | Mensaje debe contener |
| --- | --- |
| `DTC_DATABASE_URL` ausente o vacía | el nombre de la variable y cómo definirla |
| motor no admitido | el motor recibido y la lista de admitidos |
| base de datos inalcanzable | el motor y el host, **nunca** credenciales |
| esquema ausente | la sugerencia `dtc db init` |
| migración pendiente | la sugerencia `dtc db upgrade` |
| esquema desconocido | la revisión encontrada y la comprendida por el servicio |
| campo inválido | el campo, el valor recibido y la regla incumplida |
| pin duplicado | el pin y los dos acumuladores en conflicto |
| conflicto concurrente | que la configuración cambió durante la edición |
