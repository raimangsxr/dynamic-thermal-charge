# Phase 1 — Data Model: Configuración y histórico en base de datos

**Feature**: `001-config-database` | **Fecha**: 2026-08-26

Reglas transversales, derivadas de `research.md`:

- Todo instante se almacena en **UTC** (D8). Los horarios de la ventana de carga
  (`start_time`, `end_time`) son **reglas locales**, no instantes, y se almacenan como texto
  `HH:MM`.
- Las magnitudes físicas se almacenan en **enteros**: vatios y minutos. Nunca kilovatios ni
  horas en coma flotante. Coherente con la decisión de diseño ya vigente en el proyecto.
- Las claves ajenas se aplican de verdad porque el engine de SQLite activa
  `PRAGMA foreign_keys = ON` en cada conexión (D6).
- Ninguna tabla almacena secretos. La cadena de conexión y la clave de AEMET viven en
  variables de entorno; de AEMET solo se guarda **el nombre de la variable** a consultar.

---

## Tablas de configuración

### `installation`

Fila única en esta fase (una instalación por base de datos, ver Assumptions de la spec).

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | |
| `name` | texto | no | no vacío |
| `revision` | entero | no | ≥ 1. Bloqueo optimista (D9); se incrementa en cada edición |
| `max_total_power_w` | entero | no | > 0 |
| `slot_minutes` | entero | no | > 0, ≤ 60, divisor exacto de 60 |
| `window_minutes` | entero | no | > 0, múltiplo de `slot_minutes`. Derivado del horario cuando existe |
| `timezone` | texto | sí | zona IANA resoluble |
| `start_time` | texto `HH:MM` | sí | minutos desde medianoche múltiplos de `slot_minutes` |
| `end_time` | texto `HH:MM` | sí | igual regla; distinto de `start_time` |
| `weekdays` | texto | sí | enteros 0–6 (lunes=0) separados por comas, **en orden ascendente y sin repetidos**, p. ej. `0,1,2,3,4`. El formato es normativo: se escribe siempre así y se rechaza cualquier otra representación al leer |
| `log_level` | texto | no | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `state_file` | texto | no | ruta de la caché local del plan activo (D7); no vacía |
| `poll_seconds` | real | no | > 0 |
| `retention_days` | entero | sí | > 0, o `NULL` para retención ilimitada |
| `created_at` | instante UTC | no | |
| `updated_at` | instante UTC | no | |

`timezone`, `start_time`, `end_time` y `weekdays` son todos nulos o todos no nulos: o hay
horario, o la ventana se define solo por `window_minutes`.

### `weather_config`

Cero o una fila por instalación.

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | |
| `installation_id` | entero, FK → `installation.id` | no | `ON DELETE CASCADE`, único |
| `provider` | texto | no | `simulated` o `aemet` |
| `aemet_municipality_code` | texto | sí | exactamente 5 dígitos. Obligatorio si `provider = aemet` |
| `aemet_api_key_env` | texto | sí | nombre de variable de entorno, no vacío. **Nunca el valor** |
| `aemet_timeout_seconds` | real | sí | > 0 |
| `simulated_average_temperature_c` | real | sí | obligatorio si `provider = simulated` |
| `simulated_minimum_temperature_c` | real | sí | ≤ media |
| `fallback_average_temperature_c` | real | sí | |
| `fallback_minimum_temperature_c` | real | sí | ≤ media de reserva |
| `watchdog_retry_minutes` | entero | no | > 0, por defecto 15 |
| `watchdog_refresh_minutes` | entero | no | > 0, por defecto 180 |

### `heater`

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | clave interna |
| `installation_id` | entero, FK → `installation.id` | no | `ON DELETE CASCADE` |
| `heater_id` | texto | no | identificador de dominio. No vacío. **Único por instalación** |
| `name` | texto | no | por defecto igual a `heater_id` |
| `model` | texto | sí | |
| `power_w` | entero | no | > 0 |
| `full_charge_minutes` | entero | no | > 0 |
| `target_charge` | real | no | 0 ≤ v ≤ 1 |
| `priority` | entero | no | mayor se atiende primero |
| `enabled` | booleano | no | |
| `position` | entero | no | orden estable de presentación; único por instalación |

Restricción única: (`installation_id`, `heater_id`).

### `output_config`

Exactamente una fila por acumulador.

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | |
| `heater_id` | entero, FK → `heater.id` | no | `ON DELETE CASCADE`, único |
| `kind` | texto | no | `simulated` o `gpio` |
| `pin` | entero | sí | 0 ≤ pin ≤ 27. **Obligatorio si `kind = gpio`**. Único entre las salidas `gpio` de la instalación |
| `active_high` | booleano | no | |

La unicidad del pin es **por instalación y solo entre salidas `gpio`**; varias salidas
`simulated` pueden tener `pin` nulo. Esta condición se valida en la capa de dominio además
de en el esquema, porque un índice único parcial no se expresa igual en ambos motores.

### `thermal_profile`

Cero o una fila por acumulador.

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | |
| `heater_id` | entero, FK → `heater.id` | no | `ON DELETE CASCADE`, único |
| `target_temperature_c` | real | no | |
| `design_outdoor_temperature_c` | real | no | **estrictamente menor** que la objetivo |
| `thermal_factor` | real | no | > 0 |
| `min_charge` | real | no | 0 ≤ min ≤ max ≤ 1 |
| `max_charge` | real | no | |

Invariante entre tablas: si existe algún `thermal_profile` en la instalación, debe existir
`weather_config`. Se valida en dominio, no en esquema.

---

## Tablas de histórico

Todas son de **solo inserción**. Nada en el sistema las actualiza; solo la retención las
elimina.

**Alcance de la retención, por tabla.** `prune()` no actúa sobre todas por igual:

| Tabla | ¿La borra la retención? | Criterio |
| --- | :---: | --- |
| `plan` | sí | `created_at` anterior al corte **y** `window_end <= now` (ver identificación del plan activo) |
| `plan_slot` | sí | en cascada al borrar su plan |
| `plan_allocation` | sí | en cascada al borrar su plan |
| `forecast` | sí | `retrieved_at` anterior al corte y sin plan vivo que la referencie |
| `output_transition` | sí | `occurred_at` anterior al corte |
| `config_change` | **no** | **queda excluida de la retención** |

`config_change` se excluye a propósito. Es la única traza de qué se cambió en la
configuración y cuándo, en un sistema que conmuta cargas eléctricas reales; su volumen es de
decenas de filas al año, no de decenas de miles. Borrarla para ahorrar kilobytes destruiría
la respuesta a «¿quién bajó la potencia máxima el mes pasado?». Si algún día crece, tendrá su
propia retención, más larga y separada.

### `forecast`

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | |
| `installation_id` | entero, FK → `installation.id` | no | `ON DELETE CASCADE` |
| `forecast_date` | fecha | no | día al que se refiere la predicción |
| `average_temperature_c` | real | no | |
| `minimum_temperature_c` | real | sí | |
| `maximum_temperature_c` | real | sí | |
| `source` | texto | no | `aemet`, `simulated` o `fallback`. Satisface FR-017 |
| `municipality` | texto | sí | cuando el proveedor lo devuelve |
| `retrieved_at` | instante UTC | no | |

Índice: (`installation_id`, `retrieved_at`) para la retención.

### `plan`

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | |
| `installation_id` | entero, FK → `installation.id` | no | `ON DELETE CASCADE` |
| `installation_revision` | entero | no | revisión de configuración con la que se generó. Responde «con qué configuración se planificó esta noche» |
| `forecast_id` | entero, FK → `forecast.id` | sí | `ON DELETE SET NULL` |
| `window_start` | instante UTC | no | |
| `window_end` | instante UTC | no | > `window_start` |
| `slot_minutes` | entero | no | resolución vigente al planificar |
| `created_at` | instante UTC | no | |

Índice: (`installation_id`, `created_at`).

**Identificación del plan activo.** La retención no puede eliminar el plan activo (FR-023),
así que hace falta un criterio que no dependa de estado externo. La regla es:

> Un plan está **activo** si `window_end > now`. El plan activo es, entre los que cumplen esa
> condición, el de `created_at` mayor.

`prune()` protege por tanto **todo** plan con `window_end > now`, no solo el más reciente: un
plan futuro ya calculado tampoco debe desaparecer. No se añade columna de marca porque un
booleano `is_active` sería estado derivado que habría que mantener sincronizado, y quedaría
mal si el proceso muere entre dos escrituras. La condición temporal es autosuficiente y no
puede desincronizarse.

Esta regla es independiente de la copia local en fichero (research D7): el fichero es la
fuente de reanudación del controlador, y esta condición es la que protege la fila de
auditoría correspondiente.

### `plan_slot`

Un intervalo asignado a un acumulador dentro de un plan.

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | |
| `plan_id` | entero, FK → `plan.id` | no | `ON DELETE CASCADE` |
| `heater_id` | texto | no | identificador de dominio, **no** clave ajena |
| `slot_start` | instante UTC | no | |
| `slot_end` | instante UTC | no | |

`heater_id` se guarda como texto y no como clave ajena a propósito: el histórico debe
sobrevivir al borrado de un acumulador (FR-033). Un plan de hace seis meses sigue siendo
legible aunque su acumulador ya no exista.

Restricción única: (`plan_id`, `heater_id`, `slot_start`).

### `plan_allocation`

Resumen por acumulador de un plan: lo asignado y lo que quedó sin atender (FR-016).

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | |
| `plan_id` | entero, FK → `plan.id` | no | `ON DELETE CASCADE` |
| `heater_id` | texto | no | no clave ajena, mismo motivo |
| `requested_minutes` | entero | no | ≥ 0 |
| `allocated_minutes` | entero | no | ≥ 0 |
| `unmet_minutes` | entero | no | ≥ 0. Deja de vivir solo en un `WARNING` del log |

Restricción única: (`plan_id`, `heater_id`).

### `output_transition`

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | |
| `installation_id` | entero, FK → `installation.id` | no | `ON DELETE CASCADE` |
| `heater_id` | texto | no | no clave ajena, mismo motivo |
| `state` | booleano | no | estado **resultante**. Solo se inserta cuando cambia (FR-018) |
| `occurred_at` | instante UTC | no | |
| `plan_id` | entero, FK → `plan.id` | sí | `ON DELETE SET NULL`. Plan que motivó la transición |

Índice: (`installation_id`, `occurred_at`).

### `config_change`

Auditoría de las ediciones (FR-036).

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | |
| `installation_id` | entero, FK → `installation.id` | no | `ON DELETE CASCADE` |
| `revision_before` | entero | no | |
| `revision_after` | entero | no | `= revision_before + 1` |
| `entity` | texto | no | `installation`, `heater`, `output`, `thermal`, `weather` |
| `entity_key` | texto | sí | `heater_id` cuando aplica |
| `field` | texto | sí | nulo en altas y bajas de acumulador |
| `old_value` | texto | sí | representación textual. Nulo en un alta |
| `new_value` | texto | sí | nulo en una baja |
| `action` | texto | no | `set`, `add`, `remove` |
| `occurred_at` | instante UTC | no | |

No guarda identidad de operador: en esta fase no hay autenticación. Se añadirá con la API.

### `alembic_version`

Gestionada por Alembic. El servicio la **lee** con Core al arrancar para aplicar la puerta de
versión de esquema (D5); nunca la escribe.

---

## Relaciones

```text
installation 1─1 weather_config
installation 1─N heater ──1─1 output_config
             │            └─0..1 thermal_profile
             ├─N forecast ──0..N plan
             ├─N plan ──N plan_slot
             │        └──N plan_allocation
             ├─N output_transition
             └─N config_change
```

---

## Correspondencia con el dominio existente

La conversión fila → dataclass es explícita y no cambia ninguna firma del núcleo. Los
`dataclass(frozen=True)` de `models.py` se conservan **sin modificar**, incluidas sus
validaciones en `__post_init__`, que siguen siendo la última línea de defensa: cargar la
configuración desde la base de datos construye esos mismos objetos y por tanto no puede
producir una configuración que el planificador considere inválida.

| Tabla | Dataclass |
| --- | --- |
| `installation` (parte de sitio) | `SiteConfig` |
| `installation` (parte de horario) | `ScheduleConfig` |
| `installation` (nivel de log) | `LoggingConfig` |
| `installation` (ejecución) | `RuntimeConfig` |
| `weather_config` | `WeatherConfig` + `AemetConfig` + `SimulatedForecastConfig` + `WeatherWatchdogConfig` |
| `heater` + `output_config` + `thermal_profile` | `Heater` + `OutputConfig` + `ThermalProfile` |
| conjunto completo | `AppConfig` |

`AppConfig` gana un campo nuevo para la retención. Ninguna otra firma pública cambia.

---

## Reglas de validación, y dónde vive cada una

La validación está deliberadamente en tres capas, de menos a más específica.

| Capa | Qué garantiza | Por qué ahí |
| --- | --- | --- |
| **Esquema** (tipos, `NOT NULL`, FK, únicos, `CHECK` portables) | integridad estructural | protege incluso contra escrituras hechas por fuera del servicio |
| **Dominio** (`__post_init__` de las dataclasses) | invariantes de una entidad y del conjunto | reutiliza sin cambios lo ya probado; se aplica igual venga el dato de donde venga (Principio III) |
| **Validador de configuración completa** | invariantes que cruzan tablas: alineación del horario con `slot_minutes`, unicidad de pines `gpio`, presencia de proveedor meteorológico si hay perfil térmico | son las reglas que una edición aislada puede romper; se comprueban sobre el resultado completo antes de confirmar la transacción (FR-034) |

Un `CHECK` solo se usa cuando se expresa idénticamente en ambos motores. Los invariantes que
requieren índices parciales o expresiones específicas de un motor se validan en dominio, para
no divergir entre SQLite y PostgreSQL (FR-002).

---

## Transiciones de estado

**Configuración**: `ausente` → `sembrada` → `editada (revision N)` → … La revisión solo
crece. No hay borrado de la instalación en esta fase.

**Esquema**: `ausente` → `inicializado (revisión R)` → `migrado (R+1)`. Una revisión
desconocida es terminal para el arranque: rechaza, no degrada (D5).

**Salida de un acumulador**: `OFF` → `ON` → `OFF`. Cada arista genera una fila en
`output_transition`. El estado inicial de todo arranque es `OFF` (Principio I) y ese estado
inicial **no** se registra como transición, porque no hay cambio observado: se registra la
primera vez que una salida pasa a `ON`.
