# Implementation Plan: Prueba manual de relés

**Branch**: `005-relay-test-mode` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: `/specs/005-relay-test-mode/spec.md` aprobado

**Constitución aplicada**: 1.1.0 · **Depende de**: `001-config-database`, `002-config-api` y
`003-web-panel`; reutiliza heartbeat/runner de `004-home-assistant` sin exponer test por MQTT.

## Summary

Añadir una sesión temporal y exclusiva de prueba para accionar relés configurados. API y
controlador siguen separados por la base de datos: la API autentica y escribe intención; solo el
controlador conmuta y confirma. Una credencial aleatoria entregada una vez identifica al cliente o
pestaña propietaria sin inferir identidad humana.

El cierre intenta OFF en todas las salidas. Si una falla, la sesión queda terminal pero se arma un
`fault latch` persistente/generacional que impide automático, nuevas pruebas y cambios de mapping.
Solo el controlador puede limpiar el latch tras un barrido OFF completo confirmado por el driver
o verificado por una futura frontera de feedback; el automático vuelve en un ciclo posterior.

Auditoría de test es best-effort y expone degradación sin preceder ni bloquear seguridad. El
resultado terminal se consulta directamente por `session_id`. Panel usa dos cadencias separadas:
estado 1 s durante sesión/pendientes/recuperación y lease 5 s solo desde owner visible.

Decisiones: [research.md](./research.md); persistencia: [data-model.md](./data-model.md);
interfaces: [contracts/](./contracts/); validación: [quickstart.md](./quickstart.md).

## Technical Context

**Language/Version**: Python 3.12+; TypeScript 5.9; Angular 22.

**Primary Dependencies**: stdlib `secrets`/`hashlib`; SQLAlchemy Core/Alembic (`db`);
FastAPI/Pydantic (`api`); Angular/RxJS existentes. No se añaden dependencias.

**Storage**: SQLite local o PostgreSQL remoto con semántica idéntica. Alembic
`0004_relay_test_mode` crea cuatro tablas: control singleton con latch/degradación, sesiones,
resultados por salida y eventos.

**Testing**: pytest con repositorios/reloj/driver/heartbeat falsos; Vitest/jsdom con temporizadores
falsos y HTTP interceptado. Sin hardware, red remota ni sleeps reales.

**Target Platform**: Raspberry Pi 2B ARMv7 32 bit, ~1 GB, systemd; Angular compilado fuera.

**Project Type**: paquete/controlador Python, API FastAPI independiente y SPA Angular/nginx.

**Performance Goals**: confirmación ≤2 ciclos sanos; API <500 ms p95 con SQLite; estado 1 s solo
durante test/pendientes/recuperación; lease 5 s; trabajo O(n), n≤20; bundle inicial existente
<500 kB bruto/<150 kB transferido.

**Constraints**:

- OFF ante ambigüedad; intención nunca equivale a estado físico.
- Solo controlador importa driver y puede activar/terminar/limpiar latch.
- Una sesión por instalación; owner por Bearer + credencial cliente.
- Lease por defecto `max(3 × controller_poll_seconds, 30 s)`; GET nunca renueva.
- Fault latch y latch local bloquean automático hasta OFF completo y ciclo posterior.
- Sesión o latch bloquean cambios de configuración en frontera de repositorio, no solo HTTP.
- Revisión, runner, lease y límite se revalidan antes de conmutar.
- Auditoría nunca bloquea seguridad; su degradación es observable best-effort.
- Credencial clara solo en respuesta inicial y `sessionStorage`.

**Scale/Scope**: una instalación, una sesión, hasta 20 acumuladores; fuera de alcance MQTT/HA,
roles humanos, pines sin acumulador y bypass manual del latch.

## Constitution Check

*GATE: superado antes de Phase 0 y revalidado tras Phase 1.*

### I. Seguridad física primero — PASA

- API no toca GPIO. Inicio/cierre/recuperación recorren todas las salidas OFF.
- OFF parcial arma latch persistente y local; automático queda bloqueado hasta OFF completo y CAS.
- Un ciclo separado evita OFF→ON automático inmediato. No existe endpoint de limpieza.
- Apagado continúa tras fallos individuales; ids obsoletos y exceso se rechazan sin otras salidas.
- Reinicio inicializa OFF y no reproduce intención anterior.

### II. Núcleo puro, bordes explícitos — PASA

- `RelayTestRepository` y recorder son protocolos inyectables; SQL queda en `persistence/`, HTTP
  en `api/`, GPIO tras `OutputDriver`.
- `service.py` arbitra; `controller.py` ejecuta conjuntos/barridos. Scheduler/thermal/model no cambian.
- API mantiene guardas de imports de controlador/driver.

### III. Configuración validada — PASA

- Sesión fija `installation_revision`; cualquier cambio provoca cierre.
- Toda escritura de configuración comprueba atómicamente sesión/latch para preservar mapping de
  recuperación en API, CLI y futuras interfaces.
- Migración portable/versionada; gate exige head `0004`.
- Credencial usa 256 bits aleatorios, digest persistido y comparación constante.

### IV. Continuidad y degradación observable — PASA

- Fuera de test se conserva plan persistido. Durante test/latch, pérdida de coordinación fuerza OFF
  y bloquea automático localmente hasta reconciliar.
- Entrada, órdenes, resultados, latch y recuperación intentan auditoría; transiciones físicas siguen
  en `output_transition`.
- Fallo de auditoría marca degradación best-effort y nunca precede/condiciona OFF o latch.
- Se registran transiciones de entrada/salida de degradación, no cada ciclo.

### V. Tests deterministas — PASA

- Matrices para ownership, cadencias, terminal por id, límites, CAS, caída SQL, OFF parcial,
  persistencia/recuperación del latch y auditoría fallida.
- Driver, repositorio, reloj, wait, heartbeat, temporizadores y visibilidad son dobles.
- Suite Python/frontend/build completa obligatoria.

### VI. Simplicidad y stdlib — PASA

- Sin dependencias/procesos nuevos. Singleton y tres tablas de detalle reutilizan infraestructura.
- Generación CAS es el mínimo necesario para impedir limpieza obsoleta.
- Coordinador frontend específico evita alterar el polling global existente.

### Restricciones de plataforma — PASA

- DDL/transacciones usan subconjunto SQLite/PostgreSQL.
- Sin build Node en Pi ni acceso GPIO desde API.
- Lecturas indexadas, O(n≤20), temporizadores acotados a sesión.

**Puerta post-diseño: PASA sin desviaciones.**

## Project Structure

### Documentation

```text
specs/005-relay-test-mode/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/{http-api,controller-coordination,panel}.md
└── checklists/requirements.md
```

### Source affected (future implementation only)

```text
src/dynamic_thermal_charge/
├── controller.py                   # barrido completo y resultados individuales
├── service.py                      # arbitraje auto/test/latch local y ciclo posterior
├── cli.py                          # composición de repositorio/recorder; todas las salidas
├── drivers.py                      # confirmación aceptada y audit best-effort
├── persistence/
│   ├── __init__.py                 # tipos/protocolos/errores
│   ├── schema.py                   # relay_test_* y restricciones
│   ├── relay_test.py               # coordinación CAS y consulta terminal
│   ├── repository.py               # guardia config por sesión/latch
│   ├── history.py                  # retención integrada
│   ├── bootstrap.py, gate.py
│   └── migrations/versions/0004_relay_test_mode.py
└── api/
    ├── security.py, schemas.py, errors.py
    └── routes/{relay_test,config,history}.py

frontend/src/app/
├── app.routes.ts, app.ts
├── core/{api,api.types,relay-test-session}.ts
└── relay-test/{relay-test.ts,html,css,spec.ts}

tests/
├── test_controller.py, test_service.py
├── test_persistence_{relay_test,schema,retention}.py
├── test_api_{relay_test,security,config,history}.py
└── test_deployment.py, test_api_guards.py

deploy/environment.example
README.md
```

**Structure Decision**: conservar web existente. `persistence/relay_test.py` es el canal entre
procesos; `service.py` posee arbitraje/latch local; `controller.py` es único camino físico. La
guardia de configuración vive en repositorio para cubrir todas las interfaces. La ruta Angular
diferida tiene coordinador propio de dos temporizadores.

## Major Architectural Decisions

1. Sesión terminal y latch son estados separados: terminal permite consulta; latch bloquea gobierno.
2. Latch se limpia exclusivamente tras OFF completo con CAS generacional; nunca desde HTTP.
3. Ownership es capacidad de cliente entregada una vez, no identidad humana ni Bearer compartido.
4. Auditoría retorna éxito/fallo y publica degradación best-effort fuera del camino crítico.
5. Consulta actual y terminal son endpoints distintos; terminal se conserva según retención.
6. Polling de estado 1 s y lease 5 s son temporizadores independientes; GET no prolonga lease.
7. Configuración se bloquea en repositorio durante sesión/latch para preservar mapping físico.

## Migrations and Compatibility

- `0004` crea `relay_test_control`, `relay_test_session`, `relay_test_output`, `relay_test_event`;
  no altera configuración, heartbeat, planes ni transiciones existentes.
- Insertar control libre por instalación. Seeds futuros deben crearlo junto con instalación.
- Binarios head `0003` rechazan BD migrada; API/controlador/MQTT se actualizan como unidad antes de
  `dtc db upgrade`.
- API v1 es aditiva. Config writes ganan conflictos por sesión/latch. La nomenclatura de credencial
  reemplaza solo borradores no desplegados.
- `output_transition.plan_id=NULL` conserva compatibilidad para cambios manuales.
- Downgrade exige procesos detenidos, sin sesión/latch y OFF verificado; luego elimina tablas. No
  hay conversión de datos.
- Terminales desaparecen al vencer `retention_days`; clientes deben tratar 404 como podado. Con
  retención ilimitada permanecen.

## Components Affected

- Control físico y ciclo: `controller.py`, `service.py`, `cli.py`, `drivers.py`.
- Persistencia/migración: schema, nuevo repositorio, guardia config, retención, bootstrap y gate.
- API: seguridad de credencial, modelos/errores, relay-test, config e histórico.
- Frontend: ruta/tarjetas, coordinador de sesión, API tipada, navegación/indicador.
- Operación/tests: entorno, README y suites Python/Angular/deployment.

## Important Risks

| Riesgo | Impacto | Mitigación / límite |
| --- | --- | --- |
| Driver no tiene feedback mecánico | `confirmed` solo prueba aceptación GPIO | Terminología explícita; futura verificación detrás del barrido |
| OFF falla y SQL también | Latch persistente no puede escribirse al instante | Latch local bloquea; reconciliar antes de automático; reinicio exige OFF completo |
| Recuperación obsoleta compite con fallo nuevo | Podría limpiar indebidamente | `fault_generation` + CAS |
| Bearer compartido no atribuye persona | Auditoría sin nombre humano | Credencial cliente, digest, lease corto, TLS; roles fuera de alcance |
| Auditoría falla de forma amplia | Marcador puede fallar también | Log + marcador best-effort; seguridad nunca depende de ambos |
| GET cada 1 s sobre PostgreSQL remoto | Carga/latencia durante sesión | Solo sesión/pending/recuperación, consulta indexada y n≤20 |
| Retención poda terminal solicitado tarde | GET por id devuelve 404 | Contrato explícito; retención ilimitada disponible |
| Config cambia por proceso antiguo | Mapping de recuperación ambiguo | Gate `0004` y despliegue unitario; repositorio nuevo bloquea todas las vías |

## Complexity Tracking

No hay violaciones constitucionales. La generación del latch y el segundo temporizador responden a
requisitos aprobados de seguridad/concurrencia, no a abstracciones hipotéticas.
