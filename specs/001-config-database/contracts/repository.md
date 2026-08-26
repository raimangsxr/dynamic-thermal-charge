# Contract — Frontera de persistencia

**Feature**: `001-config-database`

Contrato interno exigido por el Principio II: el acceso a datos es un borde inyectable y
sustituible en pruebas. El planificador, el modelo térmico y el controlador dependen de
estos `Protocol`, nunca de SQLAlchemy.

## Errores de dominio

Todo fallo de persistencia se traduce a un error de dominio **en el borde**. Ninguna
excepción de SQLAlchemy, de `pg8000` ni de `sqlite3` cruza la frontera: es la misma regla que
`GpioDriverError` ya aplica al hardware.

| Error | Cuándo |
| --- | --- |
| `ConfigStoreError` | raíz de la jerarquía |
| `ConfigStoreUnavailableError` | base de datos inalcanzable, red caída, tiempo de espera agotado |
| `ConfigStoreEmptyError` | esquema presente, sin configuración |
| `SchemaVersionError` | esquema ausente, migración pendiente, o revisión desconocida |
| `ConfigValidationError` | la configuración almacenada o resultante es inválida. Lleva campo y, si aplica, acumulador |
| `ConfigConflictError` | la revisión cambió durante una edición |

`ConfigStoreUnavailableError` es la única que el bucle de control trata como **transitoria**:
conserva el plan y reintenta (Principio IV). Las demás son terminales para la operación en
curso.

## `ConfigRepository`

```text
current() -> tuple[AppConfig, int]
    Devuelve la configuración vigente validada y su revisión.
    Lanza ConfigStoreUnavailableError, ConfigStoreEmptyError,
    SchemaVersionError o ConfigValidationError.

set_field(revision, entity, entity_key, field, value) -> ConfigChange
    Aplica una edición sobre la revisión indicada.
    Valida la configuración completa resultante antes de confirmar.
    Atómico: o se aplica entero, o no se aplica nada.
    Lanza ConfigConflictError si la revisión ya no es la vigente.

add_heater(revision, heater) -> ConfigChange
remove_heater(revision, heater_id) -> ConfigChange
    Mismas garantías. remove_heater no borra histórico.
```

`current()` **nunca** devuelve una configuración parcialmente válida: o devuelve un
`AppConfig` completo o lanza.

## `HistoryRecorder`

```text
record_forecast(forecast) -> ForecastRef
record_plan(plan, forecast_ref, installation_revision) -> PlanRef
record_transition(heater_id, state, occurred_at, plan_ref) -> None
prune(now, retention_days) -> PruneReport
```

**Garantía no negociable**: ningún método de `HistoryRecorder` puede propagar una excepción
al llamante. Un fallo de escritura se registra como `ERROR` y la operación devuelve un
resultado nulo o vacío (FR-019, Principio IV). La observabilidad nunca puede provocar una
parada del control.

Esto es lo contrario de `ConfigRepository`, que sí lanza. La asimetría es deliberada: sin
configuración no se puede decidir qué relé cerrar; sin registro de auditoría, sí.

## `SchemaGate`

```text
check(expected_revision) -> SchemaStatus
```

Devuelve `ok`, `missing`, `behind` o `unknown` (D5). `unknown` **rechaza el arranque**; no
existe modo degradado sobre un esquema que el servicio no comprende.

## Dobles de prueba

Cada `Protocol` tiene un doble en memoria que se puede configurar para fallar de forma
determinista. Los tests del núcleo no importan SQLAlchemy (Principio V, Principio VI).
