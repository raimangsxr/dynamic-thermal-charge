# Contract — API HTTP

**Feature**: `002-config-api`

Todas las rutas viven bajo `/api/v1`. **Todas exigen credencial excepto una**, la comprobación
de salud, que está acotada por FR-052 y no revela nada. La descripción autodescriptiva (`/docs`
y `/openapi.json`) **sí exige credencial**: enumera la superficie de la API y nadie la necesita
sin autenticar. Ninguna ruta acciona una salida.

## Autenticación

```http
Authorization: Bearer <token>
```

El token se lee de `DTC_API_TOKEN`, servido por `/etc/dynamic-thermal-charge/environment`
(modo `0600`), igual que `DTC_DATABASE_URL` y `AEMET_API_KEY`.

- Se compara con `secrets.compare_digest`, para que no se pueda deducir midiendo tiempos.
- Ausente o incorrecto → **401**, con la misma respuesta en ambos casos: no se revela en qué se
  diferencia del correcto ni si la instalación existe.
- El arranque **falla** si el token no está definido, está vacío, tiene menos de 32 caracteres o
  coincide con un valor de ejemplo evidente. La API no queda escuchando sin protección.
- Un intento rechazado se registra con la ruta y el origen. **Nunca** con el token ofrecido.

## Variables de entorno

| Variable | Obligatoria | Por defecto | Descripción |
| --- | :---: | --- | --- |
| `DTC_DATABASE_URL` | sí | — | Sin cambios respecto a la fase 1 |
| `DTC_API_TOKEN` | sí | — | Credencial compartida, ≥ 32 caracteres |
| `DTC_API_HOST` | no | `127.0.0.1` | Dirección de escucha. Por defecto **solo local** |
| `DTC_API_PORT` | no | `8080` | Puerto |
| `DTC_API_STALE_SECONDS` | no | derivada | Sobrescribe la tolerancia de vigencia |
| `DTC_API_CORS_ORIGINS` | no | vacío | Orígenes admitidos, separados por comas. Vacío = ninguno |

`DTC_API_HOST` por defecto a `127.0.0.1` es deliberado: exponer la API en la red requiere un
acto explícito.

## Respuesta de error, uniforme

```json
{
  "code": "config_conflict",
  "message": "the configuration changed while the edit was being prepared: it is now at revision 4, the edit was based on 3. Re-read the configuration and try again",
  "field": null,
  "heater_id": null
}
```

| `code` | HTTP | Cuándo |
| --- | ---: | --- |
| `unauthorized` | 401 | token ausente o incorrecto |
| `not_found` | 404 | campo, acumulador o recurso inexistente |
| `already_exists` | 409 | identificador de acumulador en uso |
| `config_conflict` | 409 | la revisión enviada ya no es la vigente |
| `validation_failed` | 422 | la configuración resultante sería inválida |
| `secret_rejected` | 422 | el valor parece una credencial |
| `bad_request` | 400 | rango temporal inverso, paginación inválida |
| `no_configuration` | 503 | la base de datos no tiene instalación |
| `schema_unusable` | 503 | esquema ausente, atrasado o desconocido |
| `store_unavailable` | 503 | base de datos inaccesible |

Ningún mensaje contiene trazas, rutas del sistema de ficheros ni fragmentos de la cadena de
conexión.

## Operaciones

### `GET /api/v1/status`

El estado del momento. La operación central, pensada para consultarse cada pocos segundos.

```json
{
  "observed_at": "2026-01-16T01:15:00Z",
  "controller": {
    "liveness": "live",
    "last_seen_at": "2026-01-16T01:14:58Z",
    "age_seconds": 2.0,
    "started_at": "2026-01-15T22:00:00Z",
    "degraded": false,
    "driver_kind": "gpio",
    "state_is_current": true,
    "multiple_controllers_suspected": false
  },
  "power": { "instant_w": 5200, "limit_w": 5200, "percent_of_limit": 100.0 },
  "heaters": [
    {
      "id": "salon", "name": "Salón", "enabled": true,
      "power_w": 2800,
      "output_on": true,
      "last_known_output_on": true,
      "changed_at": "2026-01-16T01:00:00Z"
    }
  ],
  "plan": {
    "window_start": "2026-01-16T00:00:00Z",
    "window_end": "2026-01-16T08:00:00Z",
    "slot_minutes": 30,
    "installation_revision": 3,
    "slots": [{ "start": "...", "end": "...", "heater_ids": ["salon"] }]
  },
  "forecast": {
    "date": "2026-01-16", "source": "fallback",
    "average_temperature_c": 8.0, "minimum_temperature_c": 3.0,
    "maximum_temperature_c": 13.0, "municipality": null
  },
  "allocations": [
    { "heater_id": "salon", "requested_minutes": 480,
      "allocated_minutes": 480, "unmet_minutes": 0 }
  ]
}
```

**La regla que gobierna esta respuesta**: `controller.state_is_current` es `false` cuando la
vigencia es `stale` o `never_seen`. En ese caso:

- `power` es `null`. No se publica una potencia que nadie puede confirmar.
- `output_on` de cada acumulador es **`null`**, no `false`. Son cosas distintas: `false` dice
  «está apagado», `null` dice «no tengo prueba de nada». Colapsarlas permitiría que un panel
  afirmase algo que no puede saber. El último valor registrado sigue disponible en
  `last_known_output_on`, con su `changed_at`, para que el cliente lo muestre como historia y no
  como presente.
- Un cliente que solo lea `output_on` **nunca** puede pintar un acumulador de 2,8 kW como
  cargando sin prueba. Eso es lo que exige FR-016, y es la razón de que el campo sea anulable.
- `liveness` distingue `live`, `live_degraded`, `stale` y `never_seen`.

`plan` es `null` cuando ninguna ventana contiene el instante de la consulta: no se devuelve el
último plan pasado como si estuviera vigente.

`multiple_controllers_suspected` a `true` señala que más de un controlador parece estar operando
contra esta base de datos (FR-053). Dos procesos conmutando los mismos relés es un riesgo
eléctrico; la API lo señala pero **no** intenta arbitrar ni detener a ninguno, porque no tiene ni
debe tener ese poder.

### `GET /api/v1/config` · `GET /api/v1/config/heaters/{id}`

Configuración completa, o un acumulador. Incluye `config_revision` y `schema_revision`.

**Nunca** devuelve la cadena de conexión ni el valor de la clave del proveedor. Del proveedor,
solo `api_key_env` con el **nombre** de la variable.

### `PATCH /api/v1/config`

```json
{ "revision": 3, "field": "max_total_power_kw", "value": "6.0" }
```

Modifica un campo de la instalación o del proveedor meteorológico. La `revision` es obligatoria:
es el bloqueo optimista. Responde con `ChangeResponse`.

### `PATCH /api/v1/config/heaters/{id}`

Igual, para un campo de un acumulador.

### `POST /api/v1/config/heaters`

Alta de acumulador. Cuerpo con `revision` y los datos del acumulador. **409** si el
identificador ya existe.

### `DELETE /api/v1/config/heaters/{id}?revision=N`

Baja. Arrastra salida y perfil térmico; **conserva el histórico**.

### `GET /api/v1/history/plans` · `/forecasts` · `/transitions`

| Parámetro | Por defecto | Máximo |
| --- | --- | --- |
| `from` | sin límite | — |
| `to` | sin límite | — |
| `limit` | 50 | 500 |
| `cursor` | — | — |

Orden del más reciente al más antiguo. Respuesta con `items`, `limit_applied`, `has_more` y
`next_cursor`.

El `cursor` es **opaco**: codifica el par `(instante, id)` del último elemento devuelto, no un
desplazamiento, para que una inserción entre dos páginas no provoque elementos repetidos ni
saltados. Un cursor ilegible o manipulado devuelve **400**, nunca la primera página en silencio. Un rango vacío devuelve una página vacía; `from > to` devuelve **400**. Un
`limit` mayor que el máximo se acota y `limit_applied` lo refleja.

`GET /api/v1/history/transitions` admite además `heater_id`, y sigue devolviendo transiciones de
acumuladores ya eliminados.

### `POST /api/v1/history/prune`

Aplica la retención vigente. Devuelve el recuento por tabla. Con retención ilimitada no elimina
nada y lo indica.

### `GET /api/v1/health`

La única operación **sin credencial**, y deliberadamente muda: responde `{"status": "ok"}` si el
proceso está en pie. No revela nada de la instalación, ni si la base de datos responde. Existe
para que systemd y un proxy puedan comprobar el proceso sin repartir el token.

### `GET /docs` · `GET /openapi.json`

Descripción autodescriptiva, derivada de lo realmente servido. **Exige credencial** como
cualquier otra operación. No contiene secretos ni valores reales de configuración.

## Lo que la API NO hace

- **No** acciona ninguna salida, ni directa ni indirectamente. Ninguna ruta construye un driver.
- **No** ofrece forzado manual, boost ni anulación del plan.
- **No** migra el esquema: migrar desde una petición HTTP dejaría que un cliente altere la
  estructura de la base de datos. Queda en la CLI.
- **No** sirve ficheros estáticos de interfaz.
- **No** expone `DTC_DATABASE_URL`, `DTC_API_TOKEN` ni el valor de `AEMET_API_KEY`.
- **No** arbitra entre controladores: si detecta más de uno, lo señala y nada más.
