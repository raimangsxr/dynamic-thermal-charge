# Dynamic Thermal Charge

Controlador de acumuladores térmicos con API, MQTT, panel web e integración
nativa para Home Assistant.

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

## Integración con Home Assistant

La integración nativa soporta Home Assistant Core **2026.9.1**. La instalación
manual requiere esa versión de Home Assistant, acceso de red al backend y el
token Bearer configurado en `DTC_API_TOKEN` (el puerto habitual es `8080`). El
backend debe ser accesible desde la red de Home Assistant; la integración no
usa la API del panel web.

Para instalarla:

1. Descarga el árbol de esta versión y copia exactamente
   `custom_components/dynamic_thermal_charge` a
   `/config/custom_components/dynamic_thermal_charge` (o usa el editor de
   archivos de Home Assistant).
2. Reinicia Home Assistant y espera a que termine el arranque.
3. En `Ajustes → Dispositivos y servicios → Añadir integración`, busca
   `Dynamic Thermal Charge`, selecciona `http` para una red local o `https`
   para un endpoint TLS, e introduce host, puerto y token por separado.

En HTTPS se valida siempre la cadena de confianza y el nombre del certificado;
no hay una opción para desactivar esa comprobación. Un certificado autofirmado
o cuyo nombre no coincida se rechaza. Las entradas creadas por versiones
anteriores que no guardaban protocolo se migran automáticamente a HTTP,
conservando su UUID, dispositivos y entidades.

Comprobación básica: abre el dispositivo controlador y confirma que el sensor
`State` tiene uno de `running`, `idle`, `degraded` o `error`; después revisa que
el calendario y el sensor de un acumulador muestren datos. Si no hay conexión o
autenticación, las entidades aparecen como no disponibles y no muestran una
lectura antigua como actual.

Para actualizar, sustituye el directorio por el de la nueva versión, conserva
la entrada de configuración y reinicia Home Assistant. Para desinstalar,
elimina la integración desde `Ajustes → Dispositivos y servicios`, borra
`/config/custom_components/dynamic_thermal_charge` y reinicia; los datos del
backend no se borran.

El backend sigue siendo la autoridad: Home Assistant solo lee snapshots y
envía comandos autenticados con revisión optimista. La integración consulta un
snapshot coherente cada 30 segundos y solicita una actualización inmediata tras
cualquier comando. Si falla la conexión o la autenticación, todas las entidades
quedan no disponibles y no se conserva telemetría como si fuera actual.

Se crea un dispositivo controlador y un dispositivo por acumulador. El
controlador ofrece estado, potencia total, interruptor de control automático,
botón de recálculo y calendario global. Cada acumulador ofrece clima AUTO/OFF,
temperatura interior, SOC térmico, potencia, carga confirmada, posición de
compuerta opcional, próxima carga y próximo objetivo de SOC. El clima solo
permite AUTO/OFF y modifica la consigna semanal activa; no existe un mando
manual HEAT ni un mando de compuerta. El calendario agrupa intervalos contiguos
del mismo acumulador e incluye la evolución de SOC y energía.

La instalación se identifica por un UUID persistente del backend, no por el
nombre editable ni por el host. Por ello se conservan las entidades, nombres y
áreas al renombrar o reconfigurar el endpoint. La configuración detecta
duplicados por esa identidad y permite reautenticar el token sin crear otra
instalación.

## Despliegue en Docker

En la Raspberry prepara `/srv/app/data` para el estado persistente y configura
las variables de Compose. Los servicios backend se ejecutan con una identidad
numérica no root; por defecto es `1000:1000`, y se puede cambiar mediante
`DTC_RUNTIME_UID` y `DTC_RUNTIME_GID` si la instalación usa otra identidad:

```sh
export DTC_RUNTIME_UID=1000
export DTC_RUNTIME_GID=1000
export DTC_GPIO_GID="$(stat -c '%g' /dev/gpiochip0)"
sudo install -d -m 700 -o "$DTC_RUNTIME_UID" -g "$DTC_RUNTIME_GID" /srv/app/data
sudo chown -R "$DTC_RUNTIME_UID:$DTC_RUNTIME_GID" /srv/app/data
```

El `chown` solo es necesario al preparar la instalación o al migrar datos que
fueran creados por una versión anterior ejecutada como root. El reconciliador
detecta automáticamente el GID de `/dev/gpiochip0`; en un despliegue manual,
`DTC_GPIO_GID` debe ser el GID que devuelva `stat` para ese dispositivo.

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
por el driver `lgpio` para controlar las salidas, y monta el fichero de modelo
de la Raspberry en solo lectura. La lectura del modelo no necesita root; el
grupo adicional `DTC_GPIO_GID` es el que permite al usuario del proceso abrir
el dispositivo. En `Configuración → Servicio
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
prueba. Mientras MQTT está deshabilitado, el controlador usa los dos valores
fijos globales de esa sección (temperatura interior y SOC almacenado); al
habilitarlo vuelve a exigir ambos datos recibidos por MQTT. La consigna térmica
siempre procede del horario semanal configurado para cada acumulador.

Con salidas GPIO, MQTT puede permanecer deshabilitado para realizar pruebas de
relés; cuando el controlador necesita planificar en ese modo usa los valores
fijos anteriores. La simulación explícita de acumuladores
(`mqtt_simulation_enabled`) sí bloquea el arranque GPIO y se registra como un
error crítico.

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
y permite editar consignas semanales de temperatura por acumulador. Cada
consigna contiene temperatura en °C, hora de inicio, hora de fin y días de la
semana; el inicio se incluye, el fin se excluye y el intervalo puede cruzar
medianoche. La vista previa se inicia con
`POST /api/v1/planning/preview/jobs`, se consulta con
`GET /api/v1/planning/preview/jobs/{job_id}` y se cancela con
`POST /api/v1/planning/preview/jobs/{job_id}/cancel`; el trabajo y sus checks
se conservan al recargar. `POST /api/v1/planning/activate` valida el token de
inputs y guarda las consignas y el plan conjuntamente. Por defecto la ventana es
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

El plan usa un balance físico por sala y por intervalo. En cada acumulador,
`room_thermal_capacity_kwh_per_c` (C) mide la energía necesaria para subir un
grado y `room_heat_loss_kw_per_c` (K) mide el intercambio con el exterior. La
pérdida firmada se calcula como `K × (temperatura interior − temperatura exterior)
× horas`; por eso puede ser negativa cuando fuera hace más calor. La capacidad
del almacén sigue siendo `potencia nominal × horas de carga completa`, y el SOC
recibido se convierte a kWh solo para inicializar esa energía. El plan muestra
por intervalo SOC, energía almacenada, temperatura interior, objetivo, calor
entregado, intercambio térmico y déficit de temperatura.

Los valores iniciales recomendados son C = 2,5 kWh/°C y K = 0,12 kW/°C. No se
configuran objetivos porcentuales, reservas ni factores de demanda. Si falta
telemetría interior/SOC reciente, una consigna semanal, cobertura horaria o
potencia eléctrica suficiente, la vista previa lo declara como inválido o
degradado y no cambia al modelo porcentual anterior. La edición completa de un
acumulador se guarda con una única petición `PUT /api/v1/config/heaters/{id}`.

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
