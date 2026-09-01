# Dynamic Thermal Charge

Controlador de acumuladores térmicos con API, MQTT y panel web. La única
instalación soportada es Docker Compose.

## Estructura

- `backend/`: código Python, pruebas, empaquetado, imagen y entrypoint.
- `frontend/`: aplicación Angular e imagen nginx.
- `deploy/`: Compose, reconciliador y versión desplegada.
- `openspec/` y `specs/`: diseño y especificaciones del proyecto.

## Desarrollo

```sh
python -m pip install -e 'backend[dev]'
python -m pytest backend/tests -q
cd frontend && npm install && npm test
cd frontend && npm run build
```

## Despliegue en Docker

En la Raspberry prepara `/srv/app/data` para el estado persistente y configura
las variables de Compose:

En `/etc/app/app.env` debe existir el token administrativo que usará el panel:

```dotenv
DTC_API_TOKEN=un-token-aleatorio-de-al-menos-32-caracteres
```

El primer arranque lo guarda de forma no reversible y marca la instalación como
configurada; no se solicita ninguna credencial adicional de inicialización.

```sh
export DOCKERHUB_USERNAME=rromani
export APP_VERSION=VERSION
sudo -E docker compose -f deploy/compose.yaml pull
sudo -E docker compose -f deploy/compose.yaml up -d --remove-orphans --wait --wait-timeout 120
```

Los tres contenedores backend comparten `/srv/app/data` y ejecutan una
inicialización idempotente antes de arrancar. No hay que ejecutar comandos de
inicialización ni instalar Python, Node o servicios systemd en la Raspberry.

El frontend se publica en el puerto `80`. La API solo se expone dentro de la
red Docker y el panel la consume mediante nginx.

La configuración de previsión se administra exclusivamente en `Sistema →
weather`: allí se guardan proveedor, municipio AEMET, temperaturas simuladas y
de fallback, timeout y política de actualización. La clave AEMET se reemplaza
como secreto gestionado y la API solo informa si está configurada; nunca
devuelve su valor.

La sección `Sistema → mqtt` permite desactivar el broker para instalaciones de
prueba. Mientras MQTT está deshabilitado, el controlador usa los cuatro valores
fijos globales de esa sección (temperatura, temperatura objetivo, carga
almacenada y temperatura interior); al habilitarlo vuelve a exigir telemetría
recibida por MQTT.

El panel autenticado incluye la sección `Planificación`, que consulta el plan
aceptado por el controlador en `GET /api/v1/planning` y permite editar constraints
recurrentes. `POST /api/v1/planning/preview` calcula una vista previa sin tocar el
controlador; `POST /api/v1/planning/activate` valida el token de inputs y guarda
constraints y plan conjuntamente. La telemetría MQTT de cada acumulador se
valida por separado y una muestra incompleta o de más de 15 minutos se marca como
caducada y deja ese acumulador fuera del plan.

El histórico de decisiones está disponible en `GET /api/v1/history/planning-audit`
y conserva el motivo, el estado y los déficits de cada preview o activación.
La misma vista proyecta 48 horas completas; la carga acumulada de cada
acumulador se expresa en minutos equivalentes y desciende según `Pérdida
térmica (°C/h)`, configurable en el perfil térmico de cada acumulador.

Para actualizaciones automatizadas, `deploy/reconcile.sh` lee `deploy/release`,
descarga las imágenes y aplica la versión indicada. El cronjob se instala con:

```sh
sudo /opt/app/repo/deploy/reconciler-cronjob.sh
```

La entrada se ejecuta cada cinco minutos y escribe únicamente actualizaciones o
errores, con timestamp, en `/opt/app/reconciler.log`. El reconciliador usa
`rromani` como usuario de Docker Hub, por lo que no necesita variables de
entorno adicionales.

## Desarrollo con Docker Compose

SQLite:

```sh
docker compose -f deploy/compose.dev.yaml up -d --build --wait
```

El panel queda en `http://localhost:8081`, la API en `http://localhost:8080` y
MQTT en `localhost:1883`. Configura `DTC_API_TOKEN` con al menos 32 caracteres
(si no se define, se usa un token de desarrollo que conviene rotar). Los datos
están aislados en `dev-state` y `dev-mosquitto-data`; reinícialos con `down -v`.

PostgreSQL:

```sh
docker compose -f deploy/compose.dev.yaml -f deploy/compose.dev-postgres.yaml up -d --build --wait
```

El bootstrap permanece en SQLite (`dev-postgres-state`) y PostgreSQL usa el
volumen `dev-postgres-data`; el entorno SQLite conserva sus datos en
`dev-sqlite-state`. Sus variables configurables son
`DTC_DEV_POSTGRES_HOST`, `DTC_DEV_POSTGRES_PORT`, `DTC_DEV_POSTGRES_DB`,
`DTC_DEV_POSTGRES_USER` y `DTC_DEV_POSTGRES_PASSWORD`.
Cada arranque conserva los datos existentes y aplica las migraciones pendientes
del esquema, igual que producción. Para borrar solo PostgreSQL usa
`docker compose -f deploy/compose.dev.yaml -f deploy/compose.dev-postgres.yaml down -v`.
