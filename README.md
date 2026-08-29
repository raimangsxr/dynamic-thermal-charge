# Dynamic Thermal Charge

Controlador de acumuladores térmicos con API, MQTT y frontend. Toda la
configuración persistente vive en la base de datos; el proceso solo necesita el
directorio de estado local para bootstrap y continuidad.

## Primer arranque

Instala el paquete y ejecuta:

```sh
dtc db init
```

El comando crea `bootstrap.db`, `fallback.db`, `configuration.db` y
`application.db` bajo `/var/lib/dynamic-thermal-charge` (en tests se puede
inyectar otro directorio). Imprime una credencial de onboarding exactamente una
vez. Abre el frontend, completa `/inicio` y elimina la credencial después de
usarla.

No hay que crear ni mantener ficheros de entorno para ejecutar la aplicación.
API, MQTT, meteorología, salida, logging, retención y operaciones se editan en
**Configuración del sistema** (`/configuracion-sistema`). Los secretos son
write-only: se pueden conservar, sustituir o borrar, pero nunca se devuelven.
Los nombres `DTC_DATABASE_URL`, `DTC_API_TOKEN` y demás variables solo aparecen
en la referencia de importación legada (`deploy/environment.example`); no son
configuración runtime; esa configuración antigua no se migra automáticamente.
El token se genera durante onboarding (equivalente a
`secrets.token_urlsafe`) y se almacena como digest.

## Topología de almacenamiento

* `bootstrap.db`: estado de instalación, locator del driver y leases.
* `fallback.db`: snapshot mínimo, digest administrativo, plan local y outbox.
* `configuration.db`/`dtc_config`: configuración canónica.
* `application.db`/`dtc_app`: planes, forecasts, históricos, acumuladores,
  heartbeat y logs.

SQLite permanece disponible para bootstrap y continuidad. Al seleccionar
PostgreSQL en la sección de base de datos, usa **Probar conexión**, confirma el
alcance y sigue el progreso de la migración. La saga copia ambos schemas,
verifica recuentos, relaciones y checksums, cambia el locator mediante
compare-and-swap y conserva el origen sin destruirlo. El destino es la única
autoridad después del commit.

## Operación y fallback

`dtc db doctor` muestra un diagnóstico sanitizado y nunca corrige datos por su
cuenta. Ante una indisponibilidad clasificada, el controller utiliza la última
snapshot válida dentro de su edad máxima; si falta, caduca o está corrupta,
ejecuta safe-off. Las escrituras que no pueden llegar al canonical se guardan
en la outbox local con UUID y se reconcilian por lotes, de forma idempotente,
cuando vuelve la conexión.

Durante fallback o una migración la configuración es de solo lectura. El estado
de topología, la edad de la snapshot y los eventos pendientes están disponibles
en la sección de sistema y no contienen credenciales.

## Panel web

El Panel web se sirve detrás de nginx y la API escucha en `127.0.0.1` por
defecto. Se compila fuera del dispositivo (`npm run build`); no se instala Node
en el Cortex-A7. La API viaja en claro dentro de la red local: internet no lo es,
así que termina TLS en un proxy antes de exponerla.

El panel no muestra ninguna cifra de potencia sin confirmar: un heartbeat
ausente se presenta como “sin confirmar”. Consulta la [constitución](.specify/memory/constitution.md)
para las garantías de seguridad del controlador. La configuración de cada
salida conserva explícitamente `active_high` al migrar.

## CLI útil

```sh
dtc db init
dtc db doctor
dtc db import-legacy --environment /ruta/legacy.env
dtc db import-legacy --environment /ruta/legacy.env --apply
dtc config show
dtc run --driver simulated
dtc api
dtc mqtt
```

La importación legada es la única operación que acepta explícitamente un
fichero antiguo y solo lo lee durante esa ejecución. Revisa el informe dry-run
antes de `--apply`; es idempotente y no sobrescribe el origen.

## Seguridad, backups y rollback

Protege el directorio de estado (0700) y sus bases SQLite (0600). Usa TLS para
PostgreSQL salvo que confirmes una red de confianza. Haz backups consistentes
de los cuatro ficheros SQLite y del servidor PostgreSQL. Para volver atrás tras
una migración, detén los procesos, conserva el locator del origen mediante el
comando de recuperación y reabre la generación anterior; no borres el origen
hasta validar la operación.

## Desarrollo

```sh
.venv/bin/pytest -q
cd frontend && npm install && npm test
cd frontend && npm run build
```

Los tests PostgreSQL reales se ejecutan con el marcador de PostgreSQL cuando
hay un servidor disponible; la suite SQLite cubre bootstrap, fallback, saga,
API, controller y MQTT.

## Despliegue Docker

El runtime de producción usa únicamente Docker Compose. GitHub Actions ejecuta
`make check`, compila el frontend y construye ambas imágenes sin publicarlas en
cada PR. Las imágenes solo se publican en Docker Hub cuando se publica una
GitHub Release, usando exactamente `release.tag_name` como tag de ambas
imágenes; no se usa `latest`. En ese mismo workflow `deploy/release` se
actualiza con el mismo valor, que es la versión autorizada por GitOps.

En una Raspberry nueva instala Docker, crea `/etc/app/app.env` con permisos
`0600`, prepara `/opt/app/repo` y `/srv/app/data`, clona el repositorio y
configura `DOCKERHUB_USERNAME` en `app-reconcile.service`. Activa únicamente
`app-reconcile.timer`. El reconciliador valida Compose, descarga la release y
ejecuta `docker compose up -d --remove-orphans --wait`.
