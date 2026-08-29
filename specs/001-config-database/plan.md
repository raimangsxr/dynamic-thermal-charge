# Implementation Plan: Configuración y histórico en base de datos

**Branch**: `001-config-database` | **Date**: 2026-08-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-config-database/spec.md`

**Constitución aplicada**: 1.1.0

## Summary

Sustituir el YAML como origen de configuración por una base de datos —SQLite local o
PostgreSQL remoto, seleccionable por `DTC_DATABASE_URL`— y añadir un histórico auditable de
planes, previsiones y transiciones de salida con retención configurable. Incluye edición de
la configuración por línea de comandos, porque sin ella la única vía entre la instalación
sembrada y la real sería SQL a mano, que esquiva la validación exigida por el Principio III.

Enfoque técnico: **SQLAlchemy Core sin ORM** sobre las `dataclass(frozen=True)` de dominio
ya existentes, con Alembic para migraciones versionadas fuera de la ruta de importación del
runtime. El acceso a datos vive detrás de tres `Protocol` inyectables
(`ConfigRepository`, `HistoryRecorder`, `SchemaGate`), de modo que el planificador y el
modelo térmico siguen siendo funciones deterministas sin I/O y sus tests no importan
SQLAlchemy. `models.py`, `scheduler.py`, `thermal.py`, `controller.py` y `drivers.py` no
cambian de firma.

Detalle y mediciones en [research.md](./research.md); esquema en
[data-model.md](./data-model.md); contratos en [contracts/](./contracts/).

## Technical Context

**Language/Version**: Python 3.12+ (sin cambio)

**Primary Dependencies**:

| Dependencia | Ámbito | Justificación (Principio VI) |
| --- | --- | --- |
| `SQLAlchemy>=2,<3` | extra `db` | Un único código para SQLite y PostgreSQL. Se usa **solo Core**; el ORM se descarta por introducir estado mutable (research D1) |
| `Alembic>=1.13` | extra `db` | Migraciones versionadas que conservan datos, exigidas por el Principio III. Importado solo en `db init` / `db upgrade` (D4) |
| `pg8000>=1.31` | extra `postgres` | Único driver de PostgreSQL instalable en ARMv7 sin compilador ni `libpq`: **no existe wheel `armv7l` para `psycopg2-binary`, `psycopg` ni `greenlet`** (D2) |
| `PyYAML` | **se elimina** | Deja de haber configuración en fichero |

Se prohíbe la API asíncrona de SQLAlchemy: reintroduciría `greenlet`, que sí exige compilador
en la Pi (D3).

**Storage**: SQLite local (por defecto
`/var/lib/dynamic-thermal-charge/dynamic-thermal-charge.db`) o PostgreSQL remoto vía
`postgresql+pg8000://`. Motores admitidos: exactamente esos dos. El plan activo conserva
además una caché local en fichero JSON (D7).

**Testing**: `pytest`. Unitarios del núcleo con dobles en memoria sin SQLAlchemy;
integración sobre SQLite en `tmp_path`; suite de compatibilidad con PostgreSQL **omitida por
defecto**, activada solo si existe `DTC_TEST_POSTGRES_URL` (D12).

**Target Platform**: Raspberry Pi 2B (Cortex-A7, ARMv7 32 bits, ~1 GB RAM) con systemd.
Desarrollo en macOS y Linux. PostgreSQL **siempre** externo al dispositivo.

**Project Type**: Librería con CLI, proyecto único. No hay frontend en esta fase. El
ejecutable se declara con dos nombres equivalentes: `dynamic-thermal-charge` y el alias
corto `dtc`.

**Performance Goals**: irrelevantes en régimen —una lectura de configuración por refresco de
plan y unas decenas de inserciones por noche—. Lo que importa es el **arranque**: coste
añadido < 5 s en la Pi 2B y RSS del servicio < 80 MB (D13; medido: `import sqlalchemy`
157 ms y 36 MB en la máquina de desarrollo, extrapolado ×20).

**Constraints**:

- La configuración se valida íntegramente al cargar y también antes de aplicar cada edición.
- La cadena de conexión nunca aparece en logs, ni enmascarada (D11).
- Ningún camino de fallo de base de datos puede activar una salida.
- Ningún test requiere red, PostgreSQL, hardware ni espera en tiempo real.
- El subpaquete de persistencia se importa de forma perezosa: `--help` y las rutas que no
  tocan la base de datos no pagan su coste.

**Scale/Scope**: una instalación por base de datos, del orden de 4-10 acumuladores, ~27 000
filas de histórico al año con retención por defecto de 365 días (D10). Un proceso de
servicio más operaciones puntuales de CLI.

## Constitution Check

*GATE: superado antes de Phase 0 y revisado tras Phase 1.*

### I. Seguridad física primero (fail-safe) — PASA

| Regla | Cómo se cumple |
| --- | --- |
| Salidas inicializadas en OFF | sin cambios; los drivers no se tocan |
| Ausencia o invalidez de plan ⇒ ninguna salida activa | `ConfigStoreUnavailableError`, `ConfigStoreEmptyError`, `SchemaVersionError` y `ConfigValidationError` en el arranque terminan el proceso **antes** de construir cualquier driver. Códigos de salida 1/2/3/5 del contrato de CLI |
| Esquema desconocido | rechaza el arranque; **no existe** modo degradado sobre un esquema no comprendido (D5) |
| Ids desconocidos en un plan | sin cambios. Refuerzo: `plan_slot.heater_id` es texto, no clave ajena, así que un histórico antiguo no puede reintroducir un id como si fuera vigente |
| Rutas nuevas que no conmutan hardware | `db init`, `db upgrade`, `config show`, `config set`, `config add-heater`, `config remove-heater` y `history prune` **no construyen driver alguno**. Verificable con un test que compruebe que ninguna de esas rutas instancia un driver |

### II. Núcleo puro, hardware y red en los bordes — PASA

- Tres `Protocol` nuevos (`ConfigRepository`, `HistoryRecorder`, `SchemaGate`) son la única
  frontera de datos. `contracts/repository.md` es su contrato.
- `scheduler.py`, `thermal.py`, `models.py` no importan nada de persistencia y no cambian.
- Ninguna excepción de SQLAlchemy, `pg8000` o `sqlite3` cruza la frontera: se traducen a
  errores de dominio en el borde, igual que `GpioDriverError`.
- El paquete se importa y ejecuta sin el extra `db` instalado; el subpaquete de persistencia
  es de importación perezosa.

### III. Configuración validada y explícita — PASA

Este es el principio que motivó la enmienda a 1.1.0 y el que más carga soporta.

| Regla del principio | Cómo se cumple |
| --- | --- |
| Validación íntegra al cargar, con independencia del origen | validación en tres capas (esquema / dominio / configuración completa), tabuladas en `data-model.md`. Las `__post_init__` existentes se conservan sin tocar y siguen siendo la última línea de defensa |
| Error accionable que identifica el campo | `ConfigValidationError` lleva campo y acumulador; el contrato de CLI tabula el contenido exigido de cada mensaje |
| Rechazo completo, nunca parcial | `current()` devuelve `AppConfig` completo o lanza. Cada edición valida el resultado completo dentro de la transacción antes de confirmar (FR-034) |
| Sin valores por defecto implícitos que alteren comportamiento físico | pines, potencia máxima y ventana no tienen valor por defecto; la semilla los declara explícitamente y `config show` los muestra |
| Credenciales fuera del almacén, del repositorio y de los logs | `DTC_DATABASE_URL` en entorno; de AEMET solo se guarda **el nombre** de la variable; se registran motor, host y base de datos campo a campo, nunca la URL (D11); `config set` rechaza valores con aspecto de secreto (FR-038) |
| Esquema versionado, migraciones en orden, esquema más nuevo rechaza el arranque | Alembic para migrar; puerta de versión leída con Core al arrancar (D5) |
| Estado persistido versionado y de carga tolerante | `PlanStore` ya lo cumple y se conserva (D7) |

### IV. Continuidad y degradación observable — PASA

- Pérdida de acceso en caliente: `ConfigStoreUnavailableError` es la **única** excepción
  tratada como transitoria. Conserva el plan y reintenta con la cadencia configurada, sin
  terminar el proceso.
- Entrada y salida del estado degradado se registran una sola vez por transición. Cubierto
  por test con reloj controlado.
- **`HistoryRecorder` no puede propagar ninguna excepción**: un fallo de auditoría se
  registra como `ERROR` y el control continúa. La asimetría con `ConfigRepository`, que sí
  lanza, es deliberada y está documentada en el contrato.
- El plan activo mantiene su copia local atómica y durable, de modo que un corte de red con
  PostgreSQL remoto no impide reanudar tras un reinicio (D7). Es la razón de que esa copia
  no se elimine.
- Toda transición de salida se registra en el log **y** en `output_transition`.

### V. Tests deterministas sin hardware — PASA

- Tres niveles de test (D12). La suite por defecto no necesita red, PostgreSQL ni hardware.
- Caminos de fallo con cobertura explícita: variable ausente, motor no admitido, base de
  datos inalcanzable en arranque y en caliente, esquema ausente, migración pendiente,
  esquema desconocido, configuración vacía, configuración inválida, fallo de escritura de
  histórico, conflicto de edición concurrente.
- Los tests de integración usan fichero temporal en lugar de memoria, para ejercitar de
  verdad WAL, las claves ajenas y las migraciones.
- Ningún test duerme en tiempo real: reloj y `wait` inyectados, como ya hace `test_watchdog`.

### VI. Simplicidad y stdlib primero — PASA con desviación justificada

- Tres dependencias nuevas, todas en **extras opcionales** (`db`, `postgres`), justificadas
  en la tabla de Primary Dependencies y en `research.md`. Ninguna en el runtime base.
- El núcleo se importa y ejecuta sin ellas instaladas.
- **Se elimina** `PyYAML` del runtime: el balance neto de dependencias base es -1.
- Se descarta el ORM precisamente por el principio: introduciría estado mutable donde el
  proyecto usa dataclasses inmutables.
- YAGNI respetado: sin capa de abstracción multi-motor propia, sin temporizador dedicado de
  retención, sin edición interactiva ni por lotes, sin API.
- La desviación —añadir dependencias a un proyecto que era de stdlib más PyYAML— se registra
  en Complexity Tracking.

### Restricciones de plataforma — PASA

- PostgreSQL siempre remoto: la instalación no ofrece opción de motor local.
- Frontend: no aplica en esta fase.
- SQLAlchemy y Alembic ya están declarados en la constitución 1.1.0 como excepción
  justificada. `pg8000` es una concreción de esa decisión y queda documentada en
  `research.md` D2.
- Zona horaria como dato de configuración: se conserva en `installation.timezone`.

**Resultado de la puerta: PASA.** Una única desviación, registrada abajo.

## Project Structure

### Documentation (this feature)

```text
specs/001-config-database/
├── plan.md              # Este fichero
├── spec.md
├── research.md          # Phase 0: 13 decisiones con mediciones
├── data-model.md        # Phase 1: esquema y validación por capas
├── quickstart.md        # Phase 1: puesta en marcha y actualización desde YAML
├── contracts/
│   ├── cli.md           # Contrato externo: comandos, códigos de salida, errores
│   └── repository.md    # Contrato interno: Protocol de persistencia
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 — lo crea /speckit-tasks, NO este comando
```

### Source Code (repository root)

```text
src/dynamic_thermal_charge/
├── models.py                  # SIN CAMBIOS de firma; AppConfig gana retención
├── scheduler.py               # sin cambios
├── thermal.py                 # sin cambios
├── controller.py              # sin cambios
├── drivers.py                 # sin cambios
├── gpio_driver.py             # sin cambios
├── weather.py                 # sin cambios de núcleo; expone el origen de la previsión
├── watchdog.py                # sin cambios
├── logging_config.py          # sin cambios
├── state.py                   # sin cambios: caché local del plan activo (D7)
├── config.py                  # SE ELIMINA la carga YAML; queda la validación de conjunto
├── service.py                 # inyecta HistoryRecorder; degradación por BD
├── cli.py                     # reestructurado en subcomandos (contracts/cli.md)
└── persistence/               # NUEVO — importación perezosa, único borde de datos
    ├── __init__.py            # errores de dominio y factoría de repositorio
    ├── url.py                 # parseo de DTC_DATABASE_URL, motores admitidos, redacción
    ├── engine.py              # engine, PRAGMAs de SQLite (D6), traducción de excepciones
    ├── schema.py              # MetaData y Table de Core
    ├── mapping.py             # fila <-> dataclass, en ambos sentidos
    ├── repository.py          # ConfigRepository: current, set_field, add/remove heater
    ├── history.py             # HistoryRecorder: nunca propaga excepciones
    ├── gate.py                # SchemaGate: puerta de versión de esquema
    ├── seed.py                # instalación de ejemplo, idempotente
    └── migrations/            # Alembic: env.py, script.py.mako, versions/

tests/
├── (los 12 módulos actuales, con test_config.py reescrito)
├── test_models.py                    # NUEVO — invariantes de dataclass, incluida la retención
├── test_persistence_url.py
├── test_persistence_schema.py
├── test_persistence_repository.py
├── test_persistence_history.py
├── test_persistence_gate.py
├── test_persistence_seed.py
├── test_persistence_retention.py
├── test_persistence_failures.py      # Principio I y IV: todos los caminos de fallo
├── test_cli_config_commands.py
└── test_postgres_compat.py           # omitido salvo DTC_TEST_POSTGRES_URL

deploy/
├── environment.example        # añade DTC_DATABASE_URL
└── systemd/…                  # la unidad deja de pasar ruta de config

deploy/install-service.sh      # instala extra db, crea la BD local, ejecuta db init
examples/*.yaml                # se conservan SOLO como documentación y referencia de semilla
README.md                      # reescribe configuración; aviso de reintroducción manual (FR-031)
```

**Structure Decision**: proyecto único, sin backend/frontend. Toda la persistencia se
concentra en el subpaquete nuevo `src/dynamic_thermal_charge/persistence/`, que es el único
lugar del código autorizado a importar SQLAlchemy. Esa concentración es lo que hace
verificable el Principio II con un test de importación: ningún módulo fuera de
`persistence/` puede importar `sqlalchemy`.

## Migración del despliegue existente

Parte del alcance, no un apéndice:

| Artefacto | Cambio |
| --- | --- |
| `deploy/environment.example` | añade `DTC_DATABASE_URL` con ejemplos de ambos motores y el aviso de modo `0600` |
| `deploy/systemd/dynamic-thermal-charge.service` | `ExecStart` sin ruta de configuración; `ExecStartPre` valida configuración y esquema; `ReadWritePaths` cubre el directorio de la base de datos |
| `deploy/install-service.sh` | instala el extra `db`; crea `/var/lib/dynamic-thermal-charge` con el propietario correcto; **no** ejecuta `db init` automáticamente si detecta un `config.yaml` previo, para no sembrar sobre una instalación que el operador va a reintroducir |
| `README.md` | sustituye toda la sección de configuración YAML; añade el procedimiento de actualización con el aviso explícito de FR-031, con énfasis en verificar pines y `active_high` antes de conectar hardware |
| `examples/home.yaml`, `examples/raspberry-pi.yaml` | se conservan como documentación y referencia de la semilla. Se añade una cabecera indicando que el runtime **ya no los lee** |
| `tests/test_deployment.py` | se amplía para verificar la unidad y el instalador nuevos |

## Complexity Tracking

| Violación | Por qué es necesaria | Alternativa más simple rechazada porque |
| --- | --- | --- |
| Añadir SQLAlchemy y Alembic a un proyecto cuyo runtime era stdlib más PyYAML (Principio VI) | La feature exige comportamiento idéntico en dos motores y migraciones versionadas que conserven datos (FR-002, FR-011, Principio III). Mitigado: ambas en extras opcionales, el núcleo funciona sin ellas, se usa solo Core, Alembic no está en la ruta de importación del runtime, y se elimina PyYAML del runtime | `sqlite3` + `pg8000` en crudo obligaría a mantener y probar a mano dos dialectos de SQL y unas migraciones propias. Más código propio, más superficie de error y peor cobertura que dos dependencias maduras. Decisión ya tomada con el usuario y ya recogida en la constitución 1.1.0 |
| Conservar la caché local del plan activo en fichero además del histórico en base de datos (aparente duplicidad de estado) | Con PostgreSQL remoto y red caída en el arranque, un plan que viviera solo en la base de datos no se podría reanudar: regresión de continuidad frente al comportamiento actual (Principio IV). Los dos almacenes tienen propósitos distintos y no compiten: el fichero es reanudación, la base de datos es auditoría | Plan activo solo en base de datos: más limpio, pero falla exactamente en el modo de fallo que esta feature introduce. Detalle en research.md D7 |
