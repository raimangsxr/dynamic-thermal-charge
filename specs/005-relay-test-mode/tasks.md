# Tasks: Prueba manual de relés

**Input**: `spec.md` aprobada, `plan.md` actualizado, `research.md`, `data-model.md`, `contracts/` y `quickstart.md`

## Phase 1: Setup

- [ ] T001 [P] Crear migración `0004_relay_test_mode` con cuatro tablas, checks, índices, seeds y downgrade seguro en `src/dynamic_thermal_charge/persistence/migrations/versions/0004_relay_test_mode.py`.
- [ ] T002 [P] Declarar tablas, enums, nulabilidad e invariantes de sesión/salida/latch/auditoría en `src/dynamic_thermal_charge/persistence/schema.py`.
- [ ] T003 [P] Definir tipos, resultados de barrido y protocolos de repositorio/recorder/driver en `src/dynamic_thermal_charge/persistence/__init__.py`.
- [ ] T004 [P] Configurar lease, cadencias y retención documentadas en `deploy/environment.example`.
- [ ] T005 [P] Crear dobles deterministas de reloj, heartbeat, repositorio, driver, runner y hasta 20 acumuladores en `tests/conftest.py`.

## Phase 2: Foundational

- [ ] T006 Hacer que gate/bootstrap exijan head `0004`, creen singleton y compongan repositorio/recorder en `src/dynamic_thermal_charge/persistence/gate.py` y `src/dynamic_thermal_charge/persistence/bootstrap.py`.
- [ ] T007 Implementar repositorio con transacciones cortas, CAS de `command_seq`/`fault_generation`, consulta actual/terminal y retención en `src/dynamic_thermal_charge/persistence/relay_test.py`.
- [ ] T008 Implementar guardia atómica de sesión/latch para todas las escrituras de configuración en `src/dynamic_thermal_charge/persistence/repository.py`.
- [ ] T009 Integrar repositorio, recorder, reloj y driver sin importar GPIO desde API en `src/dynamic_thermal_charge/cli.py` y `src/dynamic_thermal_charge/persistence/bootstrap.py`.
- [ ] T010 [P] Implementar credencial cliente de 256 bits, digest SHA-256, comparación constante y redacción en `src/dynamic_thermal_charge/api/security.py`.
- [ ] T011 [P] Añadir esquemas Pydantic anulables, respuestas safety/audit y errores uniformes en `src/dynamic_thermal_charge/api/schemas.py` y `src/dynamic_thermal_charge/api/errors.py`.
- [ ] T012 [P] Definir tipos HTTP y almacenamiento exclusivo en `sessionStorage` en `frontend/src/app/core/api.ts`, `frontend/src/app/core/api.types.ts` y `frontend/src/app/core/relay-test-session.ts`.
- [ ] T013 [P] Cubrir migración, gate, CAS, credenciales y secretos en `tests/test_persistence_schema.py`, `tests/test_persistence_relay_test.py`, `tests/test_persistence_gate.py` y `tests/test_api_security.py`.

## Phase 3: User Story 1 - Probar un acumulador (P1) 🎯 MVP

**Goal**: iniciar una sesión exclusiva y accionar cada acumulador mostrando solo estados confirmados o pendientes.

**Independent Test**: iniciar, activar y desactivar con dobles; verificar suspensión automática, `pending → confirmed`, aislamiento GPIO y rechazo fuera de sesión.

- [ ] T014 [P] [US1] Probar reclamación, `starting → active`, ownership por credencial y 403 sin mutación en `tests/test_service.py`.
- [ ] T015 [P] [US1] Probar ciclo sano, órdenes individuales, idempotencia, CAS, límite e id obsoleto en `tests/test_controller.py`.
- [ ] T016 [P] [US1] Probar POST/GET/lease/PUT, errores, nulabilidad y no exposición de credencial en `tests/test_api_relay_test.py`.
- [ ] T017 [P] [US1] Probar sesión, almacenamiento de credencial, estados no optimistas y controles asociados en `frontend/src/app/relay-test/relay-test.spec.ts` y `frontend/src/app/core/api.spec.ts`.
- [ ] T018 [US1] Implementar arbitraje auto/test, reclamación, owner digest, lease, revisión y conjunto manual en `src/dynamic_thermal_charge/service.py`.
- [ ] T019 [US1] Implementar `starting`, OFF inicial, validación heartbeat/runner/revisión/límite y activación en `src/dynamic_thermal_charge/controller.py`.
- [ ] T020 [US1] Implementar aplicación O(n), OFF-antes-ON y confirmación física CAS preservando salidas no afectadas en `src/dynamic_thermal_charge/controller.py`.
- [ ] T021 [US1] Integrar ciclo manual con runner sin alterar automático fuera de test en `src/dynamic_thermal_charge/service.py` y `src/dynamic_thermal_charge/cli.py`.
- [ ] T022 [US1] Implementar POST inicio, GET actual, lease separado y PUT propietario en `src/dynamic_thermal_charge/api/routes/relay_test.py` y `src/dynamic_thermal_charge/api/__init__.py`.
- [ ] T023 [US1] Añadir ruta diferida, navegación autenticada y vista base en `frontend/src/app/app.routes.ts`, `frontend/src/app/app.ts` y `frontend/src/app/relay-test/relay-test.ts`.
- [ ] T024 [US1] Implementar tarjetas, banner, estados y controles no optimistas en `frontend/src/app/relay-test/relay-test.html` y `frontend/src/app/relay-test/relay-test.css`.

## Phase 4: User Story 2 - Ver y terminar con seguridad (P1)

**Goal**: cerrar con OFF completo, persistir/recuperar latch, tolerar auditoría degradada y consultar terminales por `session_id`.

**Independent Test**: provocar cierre, lease, reinicio, caída SQL y OFF parcial; verificar `unknown`, latch persistente, recovery CAS y automático solo en ciclo posterior.

- [ ] T025 [P] [US2] Probar barrido OFF completo, cierre, lease, reinicio, pérdida de coordinación y latch local en `tests/test_controller.py` y `tests/test_service.py`.
- [ ] T026 [P] [US2] Probar latch persistente/generacional, reintentos parciales, limpieza CAS obsoleta, reinicio y ciclo posterior en `tests/test_persistence_relay_test.py` y `tests/test_controller.py`.
- [ ] T027 [P] [US2] Probar DELETE, terminales, `confirmed/unknown`, GET terminal por id, 404 por poda y GET sin renovación en `tests/test_api_relay_test.py`.
- [ ] T028 [P] [US2] Probar eventos, `audit_degraded`, recuperación única, fallo recorder y redacción en `tests/test_persistence_relay_test.py` y `tests/test_api_history.py`.
- [ ] T029 [P] [US2] Probar estado cada 1 s y lease cada 5 s, visibilidad, cancelación y retorno visible con temporizadores falsos en `frontend/src/app/relay-test/relay-test.spec.ts`.
- [ ] T030 [P] [US2] Medir confirmación ≤2 ciclos sanos y API <500 ms p95 con SQLite y n≤20, sin sleeps reales, en `tests/test_controller.py` y `tests/test_api_relay_test.py`.
- [ ] T031 [US2] Implementar barrido OFF best-effort de todas las salidas y estados `unknown` en `src/dynamic_thermal_charge/controller.py`.
- [ ] T032 [US2] Implementar cierre terminal, expiración, reinicio, invariantes fallidas y bloqueo local ante caída SQL en `src/dynamic_thermal_charge/service.py` y `src/dynamic_thermal_charge/controller.py`.
- [ ] T033 [US2] Implementar armado persistente, generación, reconciliación y limpieza exclusiva del controlador tras OFF completo confirmado/verificado en `src/dynamic_thermal_charge/service.py` y `src/dynamic_thermal_charge/persistence/relay_test.py`.
- [ ] T034 [US2] Bloquear configuración durante sesión/latch en HTTP y frontera de repositorio en `src/dynamic_thermal_charge/api/routes/config.py` y `src/dynamic_thermal_charge/persistence/repository.py`.
- [ ] T035 [US2] Implementar DELETE idempotente y `GET /api/v1/relay-test/{session_id}` sin revivir/renovar en `src/dynamic_thermal_charge/api/routes/relay_test.py`.
- [ ] T036 [US2] Implementar histórico cursor/filtros/retención y redacción en `src/dynamic_thermal_charge/api/routes/history.py` y `src/dynamic_thermal_charge/persistence/history.py`.
- [ ] T037 [US2] Implementar recorder best-effort y marcador de auditoría degradada sin bloquear OFF/latch en `src/dynamic_thermal_charge/drivers.py` y `src/dynamic_thermal_charge/persistence/relay_test.py`.
- [ ] T038 [US2] Implementar coordinadores independientes: estado 1 s y lease 5 s solo owner visible; GET nunca renueva, en `frontend/src/app/core/relay-test-session.ts` y `frontend/src/app/relay-test/relay-test.ts`.
- [ ] T039 [US2] Integrar ending/failed/latch/recovery/audit/unknown, 401/403 y terminal en `frontend/src/app/relay-test/relay-test.ts`, `frontend/src/app/relay-test/relay-test.html` y `frontend/src/app/core/api.ts`.

## Phase 5: User Story 3 - Encontrar el acumulador (P2)

**Goal**: mostrar hasta 20 acumuladores en orden estable, accesibles y utilizables a 320 px.

**Independent Test**: cargar 20 acumuladores variados y una instalación vacía; verificar orden, labels, teclado, estados textuales y ausencia de scroll horizontal.

- [ ] T040 [P] [US3] Probar orden, vacío, accesibilidad, teclado, estados sin color y viewport 320 px en `frontend/src/app/relay-test/relay-test.spec.ts`.
- [ ] T041 [P] [US3] Probar navegación, indicador global, lazy loading y enlace de conflicto en `frontend/src/app/app.spec.ts`, `frontend/src/app/app.routes.spec.ts` y `frontend/src/app/config/config.spec.ts`.
- [ ] T042 [US3] Completar tarjetas responsive, foco, labels y mensajes de instalación vacía en `frontend/src/app/relay-test/relay-test.html` y `frontend/src/app/relay-test/relay-test.css`.
- [ ] T043 [US3] Añadir indicador global, lazy loading y enlace desde configuración en `frontend/src/app/app.ts`, `frontend/src/app/app.routes.ts` y `frontend/src/app/config/config.ts`.
- [ ] T044 [US3] Verificar presupuesto de bundle y ausencia de dependencias nuevas en `frontend/package.json` y configuración de build.

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T045 [P] Documentar seguridad física, ownership, latch, recovery, auditoría y downgrade en `README.md`.
- [ ] T046 [P] Ajustar guardas de imports, despliegue y head de migración en `tests/test_deployment.py` y `tests/test_api_guards.py`.
- [ ] T047 [P] Reflejar ciclos, latencia, latch, auditoría, terminal por id y cadencias en `specs/005-relay-test-mode/quickstart.md`.
- [ ] T048 Ejecutar y corregir `pytest`, `npm --prefix frontend run test` y `npm --prefix frontend run build` conforme a `specs/005-relay-test-mode/quickstart.md`.

## Dependencies & Execution Order

- T001–T005 preceden T006–T013; Foundational bloquea historias.
- US1 (T014–T024) es el MVP. US2 (T025–T039) depende de sus transiciones; sus pruebas pueden prepararse en paralelo tras T013.
- US3 (T040–T044) depende de los estados/tipos de US1/US2. Polish depende de las historias seleccionadas.

## Parallel Execution Examples

- T001–T004; T010–T013; T014–T017; T025–T030; T040–T041; T045–T047 son grupos paralelizables dentro de sus dependencias.
- En US2 se pueden repartir controlador/persistencia/API/frontend entre T031–T039 por archivos y contratos.

## Implementation Strategy

1. Completar Setup + Foundational y validar migración, repositorio, credencial y CAS.
2. Entregar US1 como MVP y validar ciclo sano, ownership e aislamiento.
3. Completar US2 antes del uso físico: OFF, latch/recovery, auditoría, terminal, cadencias y latencia.
4. Completar US3 y ejecutar quickstart/suites completas.

## Format Validation

Las 48 tareas usan `- [ ] T###`; `[P]` solo marca paralelismo, `[US#]` aparece únicamente en fases de historias y todas incluyen rutas explícitas.

## Phase 7: Convergence

- [X] T049 CRITICAL Corregir el contrato de vista y el flujo de credencial propietaria en `frontend/src/app/core/api.ts`, `frontend/src/app/core/api.types.ts`, `frontend/src/app/relay-test/relay-test.ts` y `src/dynamic_thermal_charge/api/routes/relay_test.py`, de modo que el panel propietario pueda accionar exclusivamente `heater_id` confirmado per FR-003, FR-004, FR-014 y US1/AC2-4 (contradicts)
- [X] T050 CRITICAL Completar el ciclo fail-safe de sesión, parada, OFF parcial y recuperación con latch local/persistente, CAS generacional y ciclo automático posterior en `src/dynamic_thermal_charge/controller.py`, `src/dynamic_thermal_charge/service.py` y `src/dynamic_thermal_charge/persistence/relay_test.py` per Constitution I, FR-006, FR-007, FR-015 y US2/AC4-5 (partial)
- [X] T051 Revalidar runner/heartbeat, lease, revisión vigente, acumulador y límite eléctrico antes de cada conmutación manual; rechazar sin efectos y persistir resultados `rejected` o `unknown` con CAS en `src/dynamic_thermal_charge/controller.py` y `src/dynamic_thermal_charge/persistence/relay_test.py` per FR-008, FR-009, FR-013 y plan: validaciones previas (missing)
- [ ] T052 Implementar eventos de prueba, recorder best-effort, marcador de auditoría degradada y retención de eventos/sesiones terminales en `src/dynamic_thermal_charge/drivers.py`, `src/dynamic_thermal_charge/persistence/relay_test.py`, `src/dynamic_thermal_charge/persistence/history.py` y `src/dynamic_thermal_charge/api/routes/history.py` per FR-012, FR-016, FR-017 y SC-005 (missing)
- [ ] T053 Implementar el coordinador propietario con sondeo condicional de 1 s, renovación de lease a 5 s solo visible, cancelación y recuperación terminal por `session_id` en `frontend/src/app/core/relay-test-session.ts`, `frontend/src/app/core/api.ts` y `frontend/src/app/relay-test/relay-test.ts` per FR-018 y US2/AC6 (missing)
- [ ] T054 Completar la vista de prueba con orden de configuración estable, instalación vacía, estados/resultados textuales, etiquetas/foco, diseño a 320 px e indicador/enlace global de sesión en `src/dynamic_thermal_charge/persistence/relay_test.py`, `frontend/src/app/relay-test/relay-test.{ts,html,css}`, `frontend/src/app/app.ts` y `frontend/src/app/config/config.ts` per FR-010, FR-011 y US3/AC1-4 (partial)
- [ ] T055 Añadir la matriz determinista de pruebas de relay-test para controlador, servicio, persistencia, API, guardas y frontend —incluidos ownership, CAS, límite, OFF parcial, latch/reinicio, auditoría, terminales, cadencias y accesibilidad— en las rutas previstas por T013-T041 y T046 per Constitution V (missing)
- [X] T056 Formalizar esquemas Pydantic y tipos TypeScript completos para las respuestas actual, terminal y safety/audit; validar que no divergen los nombres de campos ni la nulabilidad en `src/dynamic_thermal_charge/api/schemas.py`, `src/dynamic_thermal_charge/api/routes/relay_test.py`, `frontend/src/app/core/api.types.ts` y sus pruebas per plan: contratos y tipos HTTP (partial)
- [X] T057 Documentar el modo test, ownership, latch, auditoría, recuperación y downgrade en `README.md`, y ejecutar las tres suites de quickstart en un entorno Python limpio e instalable, corrigiendo cualquier regresión propia de la feature per T045, T047 y T048 (missing)

## Phase 8: Convergence

- [X] T058 CRITICAL Persistir y armar el *fault latch* local y de almacén ante un barrido OFF parcial durante `shutdown`/parada/reinicio, manteniendo el automático bloqueado hasta un OFF completo y un ciclo posterior, en `src/dynamic_thermal_charge/controller.py` y `src/dynamic_thermal_charge/persistence/relay_test.py` per Constitution I, FR-007, FR-015 y US2/AC4-5 (partial)
- [ ] T059 CRITICAL Añadir la matriz determinista de pruebas de relay-test —incluidos parada con OFF parcial, latch/reinicio, ownership, CAS, límite, auditoría, terminales, cadencias y accesibilidad— y dejar `pytest`, la suite Angular y el build ejecutables en el entorno de quickstart, en las rutas previstas por T013-T041 y T046 per Constitution V y T055 (missing)
- [X] T060 Completar la auditoría best-effort de relay-test, su recuperación/degradación observable y la retención/consulta paginada de eventos y sesiones terminales en `src/dynamic_thermal_charge/persistence/{relay_test,history}.py`, `src/dynamic_thermal_charge/api/routes/history.py` y sus contratos/pruebas per FR-012, FR-016, FR-017, SC-005 y T052 (partial)
- [X] T061 Completar el coordinador propietario con sondeo condicional de 1 s, renovación de lease cada 5 s solo visible, cancelación de temporizadores y recuperación terminal por el `session_id` almacenado en `frontend/src/app/core/{relay-test-session,api}.ts` y `frontend/src/app/relay-test/relay-test.ts` per FR-018, US2/AC6 y T053 (partial)
- [X] T062 Completar la vista de prueba con estado global de sesión, enlace de conflicto desde configuración, orden y estados textuales estables, instalación vacía sin controles manuales, y accesibilidad a 320 px en `frontend/src/app/{app,config/config,relay-test/relay-test}.{ts,html,css}` per FR-010, FR-011, US3/AC1-4 y T054 (partial)

## Phase 9: Convergence

- [ ] T063 CRITICAL Revalidar sesión, lease, heartbeat/runner y revisión al activar y en cada ciclo `active` —incluidos ciclos sin órdenes pendientes— y, ante cualquier invalidez, barrer OFF, persistir `unknown`/terminal/latch según resultado y mantener bloqueado el automático hasta la recuperación en `src/dynamic_thermal_charge/controller.py` y `src/dynamic_thermal_charge/persistence/relay_test.py` per Constitution I, FR-007, FR-008, FR-015 y contract: controller coordination (partial)
- [ ] T064 Corregir el contrato HTTP de relay-test: exigir controlador vigente y único antes de reclamar, responder `204` cuando no exista sesión/latch/auditoría, permitir renovar durante `starting` y `active`, y reflejar todos los códigos relay-test en tipos y mensajes del panel en `src/dynamic_thermal_charge/api/routes/relay_test.py`, `src/dynamic_thermal_charge/persistence/relay_test.py`, `frontend/src/app/core/{api,api.types,errors}.ts` y `frontend/src/app/relay-test/relay-test.ts` per FR-008, FR-014, FR-018 y contract: HTTP API/panel (partial)
- [ ] T065 Completar la auditoría best-effort de cada transición de sesión y resultado de salida —incluidos renovación, solicitud de cierre, rechazo de coordinación y `unknown`— sin condicionar GPIO/OFF, y exponer su recuperación/degradación en `src/dynamic_thermal_charge/persistence/relay_test.py`, `src/dynamic_thermal_charge/drivers.py` y sus rutas de histórico per FR-012, FR-016 y SC-005 (partial)
- [ ] T066 CRITICAL Añadir pruebas deterministas de la matriz pendiente: disponibilidad/duplicidad de controlador, inicio/lease en `starting`, expiración sin orden pendiente, OFF parcial/latch/reinicio/CAS, 204 terminal/libre, auditoría de todos los resultados, límites/CAS/ownership y cadencias/accesibilidad del panel; incluir los límites de SC-001/SC-005 en `tests/test_{api_relay_test,persistence_relay_test,controller,service}.py`, pruebas de guardas y `frontend/src/app/relay-test/relay-test.spec.ts` per Constitution V, T059 y T061 (missing)
- [ ] T067 Completar y probar las restricciones portables de almacenamiento para la FK de sesión de control y las invariantes de latch/salida previstas en `src/dynamic_thermal_charge/persistence/{schema.py,migrations/versions/0004_relay_test_mode.py}` y `tests/test_persistence_schema.py` per data-model: relay_test_control/relay_test_output y T001-T002 (partial)
