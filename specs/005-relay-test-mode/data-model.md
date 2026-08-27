# Phase 1 — Data Model: Prueba manual de relés

**Feature**: `005-relay-test-mode` | **Fecha**: 2026-08-27

Instantes: UTC ingenuo en SQL y consciente fuera del mapping. Los ids de acumulador son texto para
que la evidencia sobreviva a su baja. Todas las tablas pertenecen a una instalación.

## `relay_test_control` — exclusión, latch y degradación

Una fila por instalación; es la autoridad portable para exclusión y bloqueo automático.

| Campo | Tipo | Nulo | Regla |
| --- | --- | :---: | --- |
| `installation_id` | entero, PK/FK | no | FK `installation.id`, cascade |
| `session_id` | texto, FK | sí | sesión reclamada; set null |
| `fault_latched` | booleano | no | default false; bloquea auto/sesión/config |
| `fault_generation` | entero | no | default 0; crece al armar/rearmar |
| `fault_session_id` | texto | sí | id causal, sin FK |
| `fault_reason` | texto | sí | código cerrado redactado |
| `fault_latched_at` | instante | sí | obligatorio si latch |
| `fault_recovery_attempted_at` | instante | sí | último intento |
| `fault_recovered_at` | instante | sí | último OFF completo |
| `audit_degraded` | booleano | no | default false; solo observabilidad |
| `audit_degraded_since` | instante | sí | inicio de degradación vigente |
| `updated_at` | instante | no | última mutación |

Invariantes:

- Latch implica generación >0, razón e instante.
- Reclamar exige `session_id IS NULL AND fault_latched=false`.
- Limpiar exige OFF completo y CAS por generación; fallo de recuperación rearma/incrementa.
- `audit_degraded` no participa en conmutación ni bloquea automático.
- Toda escritura de configuración exige sesión nula y latch falso en su transacción.

## `relay_test_session` — prueba solicitada

| Campo | Tipo | Nulo | Regla |
| --- | --- | :---: | --- |
| `id` | texto, PK | no | UUID aleatorio |
| `installation_id` | entero, FK | no | instalación |
| `owner_credential_digest` | texto(64) | no | SHA-256; nunca credencial clara |
| `status` | texto | no | starting/active/ending/ended/failed |
| `installation_revision` | entero | no | snapshot al iniciar |
| `requested_at` | instante | no | aceptación API |
| `activated_at` | instante | sí | tras OFF inicial |
| `lease_expires_at` | instante | no | solo renovación propietaria válida |
| `last_owner_seen_at` | instante | no | última mutación/renovación válida |
| `controller_runner_id` | texto | sí | fijado al activar |
| `ending_requested_at` | instante | sí | solicitud/causa |
| `ended_at` | instante | sí | terminal, aun con OFF no confirmable |
| `end_reason` | texto | sí | enumeración cerrada |
| `failure_detail` | texto(512) | sí | redactado |

Razones: `owner_finished`, `lease_expired`, `owner_unauthorized`, `controller_restarted`,
`configuration_changed`, `store_unavailable`, `driver_failed`, `off_sweep_failed`,
`controller_shutdown`, `start_rejected`, `no_heaters`.

- Terminal implica `ended_at/end_reason`; active/ending implica activación/runner.
- Solo controlador declara estados por resultado físico.
- OFF parcial termina `failed/off_sweep_failed`, arma latch y libera sesión atómicamente si hay SQL.
- Terminal no acepta lease/órdenes, pero se consulta por id.
- Revisión y digest son inmutables.

## `relay_test_output` — intención y resultado por acumulador

| Campo | Tipo | Nulo | Regla |
| --- | --- | :---: | --- |
| `session_id` | texto, PK/FK compuesta | no | cascade |
| `heater_id` | texto, PK compuesta | no | id de dominio |
| `heater_name` | texto(120) | no | snapshot visible |
| `position` | entero | no | orden estable |
| `power_w` | entero | no | >0; no autoridad física |
| `desired_state` | booleano | no | inicia false |
| `command_seq` | entero | no | inicia 0; monótono |
| `requested_at` | instante | sí | nulo en secuencia 0 |
| `confirmed_state` | booleano | sí | nulo si no confirmable |
| `confirmed_seq` | entero | sí | ≤ command_seq |
| `confirmed_at` | instante | sí | tras retorno correcto |
| `result` | texto | no | idle/pending/confirmed/rejected/unknown |
| `result_code` | texto | sí | estable |
| `result_detail` | texto(512) | sí | redactado |

OFF confirmado escribe `confirmed_state=false`. Si falla conserva la última confirmación honesta o
null, marca unknown y arma latch. Idempotencia puede confirmar sin driver. Rechazo por límite
restaura intención al conjunto confirmado.

## `relay_test_event` — auditoría append-only best-effort

| Campo | Tipo | Nulo | Regla |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | autoincremental |
| `installation_id` | entero, FK | no | cascade |
| `session_id` | texto | no | sin FK |
| `kind` | texto | no | enumeración cerrada |
| `heater_id` | texto | sí | salida afectada |
| `requested_state` | booleano | sí | cuando aplica |
| `result` | texto | no | accepted/confirmed/rejected/failed/recovered |
| `code` | texto | sí | razón estable |
| `occurred_at` | instante | no | reloj del proceso |
| `detail` | texto(512) | sí | sin secretos/pin/URL/traza |

Kinds: `session_start`, `session_activated`, `lease_renewed`, `output_command`,
`output_confirmed`, `session_end_requested`, `session_ended`, `session_failed`,
`ownership_rejected`, `fault_latched`, `fault_recovery_attempted`, `fault_recovered`,
`audit_recovered`.

El recorder nunca propaga. Al fallar intenta marcar degradación después de que la acción de
seguridad continúe. `output_transition` sigue registrando cambios aceptados y usa `plan_id=NULL`.

## Estado derivado

| Estado | Derivación |
| --- | --- |
| owner | digest de header coincide en tiempo constante |
| lease_current | now ≤ expiración sin reloj anómalo |
| controller_current | heartbeat/runner vigentes, sin múltiple sospechado |
| manual_control_active | active + lease/controlador + sin latch |
| automatic_control_blocked | sesión, latch persistente o latch local |
| safety_recovery_required | latch persistente/local |
| pending | secuencia pendiente y result=pending |
| confirmed | confirmed_seq=command_seq y result=confirmed |
| unknown | falta confirmación o canal/controlador no vigente |

## Transiciones

```text
libre -> starting -> active -> ending -> ended -> libre
starting/active/ending --OFF parcial--> failed + latch -> recovery
recovery --OFF parcial--> generación+1 -> recovery
recovery --OFF completo + CAS--> sin latch -> libre
libre --ciclo posterior--> automático
```

Si SQL cae, fallo+latch existe primero en memoria y se reconcilia antes de automático. Nunca se
ejecuta automático en el ciclo que activa o limpia latch.

## Concurrencia, consulta y retención

- Transacciones cortas; GPIO fuera; confirmaciones CAS.
- Índices: sesión `(installation_id,requested_at)`, evento
  `(installation_id,occurred_at,id)`, salida `(session_id,position)`.
- `GET /relay-test/{session_id}` lee sesión/salidas aunque singleton esté libre.
- Retención elimina eventos/salidas y luego terminales; protege sesión reclamada y sesión causal de
  latch activo. Histórico pagina `(occurred_at,id)` y filtra sesión/acumulador.

## Migración `0004_relay_test_mode`

1. Crear las cuatro tablas, checks e índices portables.
2. Insertar control libre/sin latch/sin degradación por instalación existente.
3. No tocar configuración, heartbeat, planes ni transiciones.
4. Downgrade: detener procesos, exigir sesión nula, latch falso y OFF verificado; eliminar en orden
   de FK.
