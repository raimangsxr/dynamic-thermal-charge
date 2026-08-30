# Entornos Docker Compose de desarrollo

Status: approved

## Goal

Disponer de dos formas reproducibles de levantar localmente toda la aplicación,
sin modificar el Compose de producción: una con SQLite y otra con PostgreSQL
como base de datos canónica, conservando SQLite para el bootstrap.

## Requirements

- R1: El Compose de producción (`deploy/compose.yaml`) mantiene sus servicios,
  imágenes, persistencia y comportamiento actuales.
- R2: El entorno SQLite de desarrollo levanta `frontend`, `backend`,
  `backend-api`, `backend-mqtt` y un broker MQTT local mediante imágenes
  construidas desde el repositorio, usando un estado local aislado y SQLite
  como único almacenamiento de la aplicación.
- R3: El entorno PostgreSQL reutiliza los servicios de aplicación y el broker,
  añade un servidor PostgreSQL persistente y espera a que esté saludable antes
  de inicializar la aplicación.
- R4: El arranque PostgreSQL crea o conserva el bootstrap en SQLite, prepara
  PostgreSQL, lo selecciona como base canónica y hace que los procesos de la
  aplicación arranquen usando PostgreSQL desde el primer arranque operativo.
- R5: Los entornos de desarrollo quedan configurados para probar el flujo
  completo sin Raspberry Pi ni servicios externos: salidas simuladas,
  previsión meteorológica simulada, MQTT habilitado contra el broker local y
  token administrativo de desarrollo configurable.
- R6: La documentación indica los comandos de arranque, puertos, configuración
  disponible y cómo aislar o reiniciar los datos de cada entorno.
- R7: SQLite y PostgreSQL usan volúmenes de estado independientes; cada arranque
  conserva los datos existentes y aplica las migraciones pendientes del esquema.
- R8: PostgreSQL permite configurar mediante variables de entorno el host, puerto,
  base de datos, usuario, contraseña y token administrativo de desarrollo.

## Acceptance

- A1: `deploy/compose.yaml` sigue pasando `docker compose config --quiet` con
  las variables de producción y conserva las cuatro pruebas existentes de
  servicios y persistencia.
- A2: `deploy/compose.dev.yaml` pasa `docker compose config --quiet`, contiene
  los cuatro servicios de aplicación y el broker MQTT, y no declara un
  servicio PostgreSQL.
- A3: La combinación documentada del Compose base y el override PostgreSQL
  pasa `docker compose config --quiet`, PostgreSQL está saludable y los
  servicios de aplicación esperan la finalización correcta de `dev-init`.
- A4: Tras levantar el entorno SQLite, una prueba de integración comprueba que
  el frontend sirve el panel y enruta `/api`, la API responde, el controlador
  usa salidas y previsión simuladas y `backend-mqtt` conecta al broker local.
- A5: Tras levantar el entorno PostgreSQL desde datos vacíos, una prueba
  comprueba que el bootstrap es SQLite y que configuración, datos y migraciones
  canónicas se crean en PostgreSQL; al reiniciar, los datos se conservan y la
  inicialización no se repite ni rompe.
- A6: `make check` pasa y la documentación permite reproducir ambos entornos
  sin depender de rutas `/etc/app` o `/srv/app` del dispositivo de producción.

## Decisions

- D1: El entorno SQLite se define en `deploy/compose.dev.yaml`; el entorno
  PostgreSQL se obtiene con ese archivo y `deploy/compose.dev-postgres.yaml`,
  manteniendo un único conjunto de servicios de aplicación.
- D2: El desarrollo usa builds locales de las imágenes existentes y puertos de
  host no conflictivos; no se introduce un servidor Angular separado ni se
  altera el runtime de producción.
- D3: Mosquitto forma parte de ambos entornos de desarrollo, con una
  configuración local sin autenticación para pruebas, y no se añade al
  Compose de producción.
- D4: Un inicializador idempotente exclusivo de desarrollo prepara el bootstrap
  SQLite, el esquema canónico y la configuración simulada; PostgreSQL no se
  usa como sustituto ni como almacenamiento del bootstrap.
