# Quickstart — API HTTP

**Feature**: `002-config-api`

## Desarrollo local

```bash
python -m pip install -e '.[dev,api]'

export DTC_DATABASE_URL="sqlite:///$(pwd)/var/dtc.db"
export DTC_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

dtc db init          # o db upgrade si ya venías de la fase 1
dtc api              # escucha en 127.0.0.1:8420
```

En otra terminal:

```bash
curl -s -H "Authorization: Bearer $DTC_API_TOKEN" localhost:8420/api/v1/status | jq
curl -s -H "Authorization: Bearer $DTC_API_TOKEN" localhost:8420/api/v1/config | jq
open http://localhost:8420/docs
```

El controlador es un proceso aparte. Para ver un estado vigente, arráncalo también:

```bash
dtc run --controller
```

Sin él, `/api/v1/status` responde con `controller.liveness` a `never_seen` y
`state_is_current` a `false`. **Eso es correcto**, no un fallo: la API no tiene prueba de nada.

## Generar el token

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Mínimo 32 caracteres. La API **se niega a arrancar** con un token vacío, corto o igual al valor
de ejemplo del fichero de entorno. Rotarlo es editar el fichero y reiniciar la API.

## Editar configuración por la API

La revisión es obligatoria en toda escritura: es lo que impide que dos clientes se pisen.

```bash
TOKEN="Authorization: Bearer $DTC_API_TOKEN"

# Leer la revisión vigente
REV=$(curl -s -H "$TOKEN" localhost:8420/api/v1/config | jq .config_revision)

# Cambiar un campo de la instalación
curl -s -X PATCH -H "$TOKEN" -H 'Content-Type: application/json' \
  -d "{\"revision\": $REV, \"field\": \"max_total_power_kw\", \"value\": \"6.0\"}" \
  localhost:8420/api/v1/config | jq

# Cambiar un campo de un acumulador
curl -s -X PATCH -H "$TOKEN" -H 'Content-Type: application/json' \
  -d "{\"revision\": $REV, \"field\": \"target_charge\", \"value\": \"0.8\"}" \
  localhost:8420/api/v1/config/heaters/salon | jq
```

Reenviar una revisión vieja devuelve **409** con el mensaje de que hay que releer. No es un
error a evitar: es la protección funcionando.

## Histórico

```bash
curl -s -H "$TOKEN" \
  'localhost:8420/api/v1/history/plans?from=2026-01-01T00:00:00Z&limit=10' | jq
curl -s -H "$TOKEN" \
  'localhost:8420/api/v1/history/transitions?heater_id=salon&limit=100' | jq
```

Paginado siempre, 50 por defecto y 500 como máximo. Nunca devuelve el histórico completo.

## Despliegue en la Raspberry Pi

Dos servicios independientes que se comunican por la base de datos:

```bash
sudo ./scripts/install-service.sh --with-api
sudoedit /etc/dynamic-thermal-charge/environment   # añade DTC_API_TOKEN

sudo systemctl start dynamic-thermal-charge        # controlador
sudo systemctl start dynamic-thermal-charge-api    # API
```

Parar la API **no** afecta a la calefacción:

```bash
sudo systemctl stop dynamic-thermal-charge-api     # el controlador sigue a lo suyo
```

Es la propiedad por la que se eligieron dos procesos. Merece la pena comprobarla una vez.

### Exponer la API en la red local

Por defecto escucha en `127.0.0.1`, solo accesible desde la propia Pi. Para llegar desde otro
equipo de tu red:

```bash
# En /etc/dynamic-thermal-charge/environment
DTC_API_HOST=0.0.0.0
```

**Sabe lo que estás haciendo antes de hacerlo.** La API sirve en claro, sin cifrado: cualquiera
con acceso a tu red puede leer el token al pasar. Para uso doméstico en una red de confianza es
razonable. Publicarla en internet **no lo es** sin poner delante un proxy inverso con TLS, y eso
queda fuera del alcance de esta fase.

Cualquiera que tenga el token puede cambiar la potencia máxima y la asignación de pines. Trátalo
como la contraseña del cuadro eléctrico, porque funcionalmente lo es.

## Diagnóstico

| Síntoma | Causa probable |
| --- | --- |
| la API no arranca, habla del token | `DTC_API_TOKEN` ausente, vacío, con menos de 32 caracteres o igual al de ejemplo |
| **401** en todo | falta la cabecera `Authorization`, o el token no coincide |
| `liveness: never_seen` | el controlador no ha arrancado nunca contra esta base de datos |
| `liveness: stale` | el controlador está parado o colgado; comprueba su unidad |
| `liveness: live_degraded` | el controlador vive pero no alcanza la base de datos o el proveedor meteorológico |
| `state_is_current: false` y `power: null` | correcto por diseño: sin latido reciente no se publica una potencia que nadie puede confirmar |
| **503** `schema_unusable` | ejecuta `dtc db upgrade`; la API nunca migra por sí misma |
| **503** `store_unavailable` | la base de datos no responde; con PostgreSQL remoto, revisa la red |
| **409** al escribir | otro cliente escribió primero; relee la configuración y reintenta |
| el navegador bloquea las peticiones | falta declarar su origen en `DTC_API_CORS_ORIGINS` |
