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
make setup   # entorno de backend en backend/.venv y dependencias del panel
make test    # pruebas de backend y de frontend
make lint    # ruff sobre el backend
make check   # test + lint + build del panel + validación de los Compose
make dev     # valida la configuración persistida
```

`make check` es la misma puerta que ejecuta CI, así que un test de frontend en
rojo o un hallazgo del linter impiden mezclar. La suite informa del porcentaje
de cobertura total y trata como error cualquier advertencia emitida por el
propio proyecto; las deprecaciones de terceros toleradas están enumeradas una a
una en `backend/pyproject.toml`.

El backend se instala en `backend/.venv`, que es el intérprete que usan `make
test` y `make lint` cuando existe. El panel se compila siempre fuera del
dispositivo.

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

El servicio `backend` recibe `/dev/gpiochip0`, que es el dispositivo utilizado
por el driver `lgpio` para controlar las salidas. En `Configuración → Servicio
→ Salidas físicas` selecciona `GPIO` como modo global y reinicia el controlador;
este cambio no se aplica a un proceso ya arrancado.

Los pines del acumulador se introducen como número GPIO, no como número físico
del conector ni como función alternativa. Por ejemplo, el pin físico 12 aparece
en muchos esquemas como `GPIO18 / PCM_CLK`: en la aplicación se debe configurar
como `18`. Para un LED que se enciende al llevar el GPIO a GND, el nivel activo
del acumulador debe ser `Bajo` (`active_high=false`).

La configuración se concentra en `/configuracion`, organizada por tareas. La
URL anterior `/configuracion-sistema` se conserva como alias y redirige a la
experiencia unificada.

La ruta `/prueba-reles` permite comprobar las salidas de los acumuladores con
una sesión exclusiva y temporal. Solo se puede iniciar con el controlador vivo
y una configuración válida; el panel muestra una salida como confirmada
únicamente cuando el controlador lo acredita, y mantiene la recuperación de
seguridad como responsabilidad del dispositivo. La duración, el sondeo y la
renovación de la sesión se ajustan en `Configuración → Servicio → Operación`.

La configuración de previsión se administra exclusivamente en `Configuración →
Integraciones → Meteorología`: allí se guardan proveedor, municipio AEMET, temperaturas simuladas y
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

La sección `Configuración → Integraciones → MQTT` permite desactivar el broker para instalaciones de
prueba. Mientras MQTT está deshabilitado, el controlador usa los cuatro valores
fijos globales de esa sección (temperatura, temperatura objetivo, carga
almacenada y temperatura interior); al habilitarlo vuelve a exigir telemetría
recibida por MQTT.

Como medida de seguridad, el controlador no arranca salidas GPIO si MQTT está
deshabilitado o si está activa la simulación de acumuladores: ambas situaciones
proporcionan telemetría no real y se registran como un error crítico.

Si una salida rechaza una conmutación, el controlador degrada únicamente esa
salida: aplica el resto de las transiciones del ciclo, la reintenta en cada
sondeo y no persiste ninguna exclusión. Una salida cuyo apagado falla se sigue
considerando cerrada, de modo que la potencia instantánea no afirma un estado
que el driver no aceptó. Mientras alguna salida esté en esa situación el
controlador se publica como degradado y el fallo se registra como crítico una
sola vez por transición.

La sección `Configuración → Planificación` permite configurar la ventana visible y el
horizonte completo, ambos entre 1 y 48 horas, con ventana no mayor que el
horizonte, además del límite total de tiempo del optimizador en segundos
(entero positivo; por defecto 120). La sección `Planificación` consulta el plan aceptado en `GET /api/v1/planning`
y permite editar constraints recurrentes. La vista previa se inicia con
`POST /api/v1/planning/preview/jobs`, se consulta con
`GET /api/v1/planning/preview/jobs/{job_id}` y se cancela con
`POST /api/v1/planning/preview/jobs/{job_id}/cancel`; el trabajo y sus checks
se conservan al recargar. `POST /api/v1/planning/activate` valida el token de
inputs y guarda constraints y plan conjuntamente. Por defecto la ventana es
de 12 horas y el horizonte de 24 horas; ambos comienzan en el primer límite de
slot que no haya pasado (el límite exacto se conserva y los instantes
intermedios avanzan al siguiente). Sin cobertura AEMET horaria continua para todo el
horizonte no se publica un plan parcial. La
telemetría MQTT de cada acumulador se valida por separado y una muestra
incompleta o de más de 15 minutos se marca como caducada y deja ese acumulador
fuera del plan.

La ventana y el horizonte se cuentan en horas de reloj de pared, y los límites de
slot caen siempre en múltiplos de la duración de slot configurada. Los dos días
del año en que cambia la hora, un horizonte de 24 horas cubre por tanto 25 horas
reales en octubre y 23 en marzo: con slots de 30 minutos son 50 y 46 slots en vez
de 48. Cada slot dura exactamente su duración configurada de tiempo real, los
límites nunca se solapan y la hora que se repite en octubre usa la previsión
horaria de esa hora de pared en sus dos pasadas.

Las constraints se editan como porcentajes de 0 a 100 en el panel y se envían a
la API como fracciones de 0 a 1. La reserva de cada acumulador es un
porcentaje multiplicativo sobre la demanda estimada (no puntos extra de SOC).
`demand_factor` escala la demanda degree-hours y la configuración global define
potencia contratada, carga base de vivienda, límite de calefacción, diseño 21/0 °C
y horizonte de feedback. La edición completa
de un acumulador se guarda con una única petición `PUT /api/v1/config/heaters/{id}`.

El histórico de decisiones está disponible en `GET /api/v1/history/planning-audit`
y conserva el motivo, el estado y las violaciones de cada preview o activación.
La misma vista proyecta el horizonte completo configurado y muestra la ventana
visible como sus intervalos iniciales; los gráficos muestran el contexto
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
