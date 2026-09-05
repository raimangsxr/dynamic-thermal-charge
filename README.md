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

Para AEMET, `aemet_query_hour` define la consulta diaria en la zona horaria de
la instalación. Tras un fallo se realizan cinco reintentos, uno por hora; si
se agotan, el controlador conserva la última previsión AEMET válida marcada
como obsoleta para seguir calculando, pero nunca habilita carga automática con
una previsión simulada o de respaldo. `replan_minutes` marca la cadencia de
replanificación y se ajusta siempre a un límite de intervalo, sin ser menor que
un intervalo de carga.

La sección `Sistema → mqtt` permite desactivar el broker para instalaciones de
prueba. Mientras MQTT está deshabilitado, el controlador usa los cuatro valores
fijos globales de esa sección (temperatura, temperatura objetivo, carga
almacenada y temperatura interior); al habilitarlo vuelve a exigir telemetría
recibida por MQTT.

Como medida de seguridad, el controlador no arranca salidas GPIO si MQTT está
deshabilitado o si está activa la simulación de acumuladores: ambas situaciones
proporcionan telemetría no real y se registran como un error crítico.

La sección `Planificación` consulta el plan aceptado en `GET /api/v1/planning`
y permite editar constraints recurrentes. La vista previa se inicia con
`POST /api/v1/planning/preview/jobs`, se consulta con
`GET /api/v1/planning/preview/jobs/{job_id}` y se cancela con
`POST /api/v1/planning/preview/jobs/{job_id}/cancel`; el trabajo y sus checks
se conservan al recargar. `POST /api/v1/planning/activate` valida el token de
inputs y guarda constraints y plan conjuntamente. El horizonte automático es
siempre de 24 horas desde el instante en que se recalcula: sin cobertura AEMET
horaria continua no se publica un plan parcial. La
telemetría MQTT de cada acumulador se valida por separado y una muestra
incompleta o de más de 15 minutos se marca como caducada y deja ese acumulador
fuera del plan.

Las constraints se editan como porcentajes de 0 a 100 en el panel y se envían a
la API como fracciones de 0 a 1. La reserva de cada acumulador es un
porcentaje multiplicativo sobre la demanda estimada (no puntos extra de SOC).
`demand_factor` escala la demanda degree-hours y la configuración global define
potencia contratada, carga base de vivienda, límite de calefacción, diseño 21/0 °C
y horizonte de feedback. La edición completa
de un acumulador se guarda con una única petición `PUT /api/v1/config/heaters/{id}`.

El histórico de decisiones está disponible en `GET /api/v1/history/planning-audit`
y conserva el motivo, el estado y las violaciones de cada preview o activación.
La misma vista proyecta 24 horas completas; los gráficos muestran el contexto
de preview cuando existe y ofrecen una alternativa textual con unidades para
cada intervalo. El resumen usa lenguaje operativo y agrupa avisos por causa.

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
