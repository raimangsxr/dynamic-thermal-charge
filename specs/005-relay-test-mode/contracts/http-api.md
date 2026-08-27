# Contract — API HTTP de prueba de relés

**Feature**: `005-relay-test-mode` | **Base**: `/api/v1/relay-test`

Todas las operaciones exigen `Authorization: Bearer <DTC_API_TOKEN>`. Mutaciones propietarias
exigen `X-Relay-Test-Credential: <client_credential>`. La credencial solo aparece al iniciar;
nunca en URL, logs ni respuestas posteriores.

## Representación

```json
{
  "session": {
    "id": "uuid",
    "status": "active",
    "owner": true,
    "requested_at": "2026-08-27T10:00:00Z",
    "activated_at": "2026-08-27T10:00:02Z",
    "ended_at": null,
    "lease_expires_at": "2026-08-27T10:00:32Z",
    "end_reason": null
  },
  "controller": {
    "state_is_current": true,
    "last_seen_at": "2026-08-27T10:00:03Z"
  },
  "safety": {
    "automatic_control_blocked": true,
    "fault_latched": false,
    "fault_session_id": null,
    "fault_reason": null,
    "fault_latched_at": null,
    "fault_recovery_attempted_at": null,
    "fault_recovered_at": null
  },
  "audit": {
    "degraded": false,
    "degraded_since": null
  },
  "heaters": [{
    "id": "salon",
    "name": "Salón",
    "position": 0,
    "power_w": 2000,
    "desired_state": false,
    "confirmed_state": false,
    "result": "confirmed",
    "result_code": null,
    "confirmed_at": "2026-08-27T10:00:02Z"
  }]
}
```

`session` puede ser null en consulta actual si hay latch/degradación sin sesión. `confirmed_state`
es `boolean|null`; null es desconocido. Solo `automatic_control_blocked=false` permite afirmar que
el automático puede gobernar.

## `POST /api/v1/relay-test`

Sin cuerpo. Exige heartbeat vigente, controlador único, configuración válida con acumuladores,
control libre y sin latch. Respuesta `202`:

```json
{
  "session_id": "uuid",
  "client_credential": "valor-entregado-una-vez",
  "status": "starting",
  "lease_expires_at": "2026-08-27T10:00:30Z",
  "state_poll_seconds": 1,
  "lease_renew_seconds": 5
}
```

No afirma suspensión automática; el panel espera `active`.

## `GET /api/v1/relay-test`

Devuelve coordinación/sesión actual. Solo `204` si no hay sesión, latch ni auditoría degradada. La
credencial opcional únicamente calcula `owner`; GET no renueva lease.

## `GET /api/v1/relay-test/{session_id}`

Consulta estable por UUID de sesión actual o terminal. Devuelve sus salidas finales y causa aunque
el singleton esté libre. No exige ownership; un header coincidente solo informa `owner=true`.
Devuelve 404 si nunca existió o fue podada. Nunca revive, renueva ni cambia sesión.

## `POST /api/v1/relay-test/{session_id}/lease`

Exige credencial propietaria. Renueva hasta `now + lease_seconds`; no revive vencida/terminal ni
acepta revisión/runner distintos o latch. Se invoca cada 5 s desde pestaña visible y es independiente
de GET.

## `PUT /api/v1/relay-test/{session_id}/heaters/{heater_id}`

Cuerpo `{"state":true}`. Exige owner, active, lease y sin latch. Prevalida id/límite, guarda
secuencia y responde `202`:

```json
{"heater_id":"salon","desired_state":true,"result":"pending","command_seq":3}
```

Estado se consulta cada 1 s durante sesión/pending. Solo `confirmed_state` representa aceptación
por GPIO.

## `DELETE /api/v1/relay-test/{session_id}`

Exige owner. Responde `202 ending`; idempotente en ending/terminal. OFF completo produce `ended`;
OFF parcial produce `failed`, arma latch y mantiene bloqueo automático. Nunca afirma OFF al aceptar.

## `GET /api/v1/history/relay-tests`

Cursor descendente `(occurred_at,id)`. Filtros: `from`, `to`, `limit`, `cursor`, `session_id`,
`heater_id`. Incluye latch/recuperación; nunca credencial, digest, pin, URL o detalle de driver.

## Errores

| HTTP | `code` | Significado |
| ---: | --- | --- |
| 401 | `unauthorized` | Bearer ausente/incorrecto |
| 403 | `relay_test_not_owner` | credencial cliente ausente/incorrecta |
| 404 | `not_found` | sesión/acumulador inexistente o podado |
| 409 | `relay_test_active` | sesión o edición bloqueada |
| 409 | `relay_test_not_active` | starting/ending/terminal |
| 409 | `relay_test_expired` | lease caducado |
| 409 | `relay_test_configuration_changed` | revisión distinta |
| 409 | `relay_test_power_limit` | conjunto excede límite |
| 409 | `relay_test_fault_latched` | recuperación OFF pendiente |
| 503 | `controller_unavailable` | heartbeat ausente/viejo/múltiple |
| 503 | `store_unavailable` / `schema_unusable` | contratos existentes |

Cuerpo uniforme `{code,message,field,heater_id}`. Rechazos no cambian salidas; 5xx no filtran
secretos/trazas.

## Compatibilidad

API v1 aditiva. La feature no está implementada, por lo que renombrar el borrador
`session_token`/`X-Relay-Test-Session` a `client_credential`/`X-Relay-Test-Credential` no migra
clientes desplegados. Configuración devuelve conflicto durante sesión o latch. OpenAPI describe
nulabilidad, ambas cadencias, seguridad y consulta terminal.
