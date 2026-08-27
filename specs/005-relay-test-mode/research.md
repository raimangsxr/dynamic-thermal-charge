# Phase 0 — Research: Prueba manual de relés

**Feature**: `005-relay-test-mode` | **Fecha**: 2026-08-27

No quedan elementos `NEEDS CLARIFICATION`. Las decisiones parten de la arquitectura existente:
controlador y API son procesos separados, SQLAlchemy Core es la frontera compartida, el
controlador publica heartbeat, el Bearer es común a la instalación y Angular usa temporizadores
inyectables y estados no optimistas.

## D1 — SQL coordina; solo el controlador toca GPIO

**Decision**: la API persiste reclamaciones e intenciones; el controlador las consume en su bucle
y es el único que llama a `OutputDriver`. `RelayTestRepository` traduce excepciones SQL a errores
de dominio y no mantiene transacciones abiertas durante I/O físico.

**Rationale**: conserva permisos de despliegue, funciona igual con SQLite/PostgreSQL y reutiliza
el patrón de heartbeat sin añadir procesos.

**Alternatives considered**: GPIO desde FastAPI rompe aislamiento; socket Unix no sirve con
procesos remotos; MQTT/colas añaden disponibilidad externa al camino de seguridad.

## D2 — Intención y confirmación son estados distintos

**Decision**: una escritura HTTP devuelve `pending`; solo el controlador, después de que el driver
retorne y mediante CAS sobre `command_seq`, escribe `confirmed`. La falta de confirmación es
`unknown`, nunca OFF.

**Rationale**: confirmar SQL no confirma GPIO. El snapshot versionado converge tras respuestas
perdidas y evita reproducir una cola.

**Alternatives considered**: respuesta optimista falsea estado; bloquear HTTP hasta otro ciclo no
elimina fallos del canal.

## D3 — Ownership por credencial de cliente

**Decision**: al reclamar se generan 32 bytes aleatorios. La respuesta entrega una única vez
`client_credential`; SQL guarda solo `SHA-256` en `owner_credential_digest`. Ordenar, renovar y
finalizar exige Bearer más `X-Relay-Test-Credential`, comparado con `secrets.compare_digest`. La
pestaña guarda id y credencial solo en `sessionStorage`.

**Rationale**: el Bearer compartido no identifica personas. La capacidad prueba posesión por el
cliente iniciador sin inventar usuarios, roles, IPs o atribución humana.

**Alternatives considered**: Bearer solo permite apropiación; IP/User-Agent son inestables;
cuentas/roles amplían alcance; token claro amplía el impacto de leer la BD.

## D4 — Exclusión portable con estado singleton

**Decision**: `relay_test_control` conserva una fila por instalación. Reclamar usa
`UPDATE ... WHERE session_id IS NULL AND fault_latched = false`. Toda escritura de configuración
consulta la misma fila en su transacción y se rechaza durante sesión o latch.

**Rationale**: evita índices parciales distintos y cierra carreras de doble inicio y cambio de
mapping durante recuperación.

**Alternatives considered**: locks en memoria no cruzan procesos; check-then-insert tiene carrera;
bloquear solo HTTP deja abiertas CLI y futuras interfaces.

## D5 — Máquina de estados y consulta terminal

**Decision**: `starting → active → ending → ended`, con `failed` terminal. Antes de `active` y de
cualquier terminal se intenta OFF. `GET /api/v1/relay-test/{session_id}` recupera sesión activa o
terminal y salidas mientras la retención la conserve, aunque ya no sea la singleton actual.

**Rationale**: la API puede caer tras pedir inicio/fin. Las fases evitan afirmar suspensión u OFF
prematuramente y la consulta recupera el desenlace tras recarga o respuesta perdida.

**Alternatives considered**: un booleano mezcla intención y realidad; reconstruir desde eventos
no conserva de forma fiable el último resultado por salida.

## D6 — Lease y sondeo usan relojes independientes

**Decision**: lease por defecto `max(3 × controller_poll_seconds, 30 s)`, renovado cada 5 s solo
por pestaña propietaria visible. Estado cada 1 s mientras la sesión esté en curso o haya orden
pendiente; se detiene tras terminal estable. Al volver visible se consulta antes de renovar.

**Rationale**: el sondeo reduce latencia visual; el lease demuestra presencia. Un GET no debe
renovar accidentalmente ni la renovación retrasar confirmaciones.

**Alternatives considered**: un poll de 5 s incumple lo aprobado; renovar con GET convierte
observadores en propietarios; WebSocket no elimina el lease.

## D7 — Fault latch persistente y generacional

**Decision**: un fallo durante cualquier barrido OFF activa `fault_latched`, incrementa
`fault_generation` y conserva causa, sesión e instante. No se evalúa automático ni se admiten
nuevas sesiones/cambios de configuración. El controlador reintenta OFF sobre todas las salidas.
Solo éxito total limpia por CAS sobre la generación observada; el automático vuelve en el ciclo
siguiente. El driver actual confirma aceptación de OFF; una futura realimentación podrá verificarlo
detrás de la misma frontera.

**Rationale**: separar latch de `session_id` deja la sesión terminal y consultable sin volverla
operable. La generación evita que una recuperación antigua borre un fallo posterior.

**Alternatives considered**: `ending` indefinido falsea desenlace; liberar sin latch puede
reenergizar; limpieza HTTP carece de prueba; latch solo en memoria se pierde al reiniciar.

## D8 — Caída del almacén mantiene latch local

**Decision**: si falla coordinación durante sesión/recuperación, el controlador fija latch local,
barre OFF y no ejecuta automático. Al volver SQL, persiste/reconcilia antes de intentar limpiar.
En arranque, una inicialización OFF completa puede confirmar recuperación; cualquier error mantiene
el gobierno automático suspendido.

**Rationale**: sin canal no se validan ownership, lease ni latch. El estado local protege el
proceso vivo y la reconciliación hace durable la decisión.

**Alternatives considered**: conservar orden manual o reanudar fila antigua puede energizar;
depender solo de systemd no demuestra OFF.

## D9 — Límite y configuración se revalidan al conmutar

**Decision**: la API prevalida; el controlador recalcula conjunto contra revisión y límite, apaga
antes de encender y rechaza solo la secuencia excesiva conservando lo confirmado.

**Rationale**: solo el controlador conoce el snapshot que aplicará y cubre carreras.

**Alternatives considered**: validar solo en API deja carrera; apagar otra carga viola la
independencia de la orden.

## D10 — Auditoría best-effort y degradación observable

**Decision**: `relay_test_event` registra intentos/resultados y `output_transition` cambios
aceptados por driver. El recorder nunca propaga y devuelve éxito/fallo. Un fallo intenta marcar
best-effort `audit_degraded`/`audit_degraded_since` en el singleton; la API lo expone aun sin
sesión. Un evento posterior permite registrar recuperación y limpiar el indicador. Ninguna
auditoría precede ni condiciona OFF, confirmación de seguridad o latch.

**Rationale**: se intenta y se hace visible la auditoría sin convertir observabilidad en autoridad
de control. El marcador separado puede sobrevivir a un fallo específico de la tabla de eventos.

**Alternatives considered**: propagar bloquea seguridad; solo log no es visible; un evento fallido
no puede representar su propio fallo.

## D11 — Retención protege terminales y latches vigentes

**Decision**: sesiones terminales/salidas se podan con `retention_days`; con retención ilimitada
permanecen. Nunca se elimina la sesión reclamada ni la referida por un latch activo. Después de una
poda válida, consultar ese id devuelve 404.

**Rationale**: respeta la política existente y mantiene el agregado recuperable durante su periodo
auditable sin crecimiento no acotado.

**Alternatives considered**: retención paralela infinita contradice configuración; reconstrucción
desde logs/eventos pierde resultados.

## D12 — UI conservadora con dos temporizadores

**Decision**: `/prueba-reles` usa tarjetas y estados no optimistas. Un coordinador posee dos
temporizadores testeables: estado 1 s y lease 5 s. No se reutiliza sin cambios el `Poller` global,
cuyo mínimo es 2 s y cuya visibilidad tiene otra semántica; sus defaults permanecen compatibles.

**Rationale**: evita cambiar accidentalmente la carga de `/status`. Una sesión y hasta 20 salidas
hacen asumible el GET de 1 s.

**Alternatives considered**: bajar globalmente el mínimo altera vistas existentes; un toggle
optimista confunde intención y estado.

## D13 — Sin dependencias ni procesos nuevos

**Decision**: reutilizar stdlib, SQLAlchemy/Alembic, FastAPI/Pydantic y Angular/RxJS actuales.

**Rationale**: el alcance no justifica Redis, broker, JWT ni librería UI.

**Alternatives considered**: añaden memoria, despliegue y fallos sin resolver necesidad aprobada.
