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

```sh
export DOCKERHUB_USERNAME=rromani
export APP_VERSION=VERSION
sudo -E docker compose -f deploy/compose.yaml pull
sudo -E docker compose -f deploy/compose.yaml up -d --remove-orphans --wait
```

Los tres contenedores backend comparten `/srv/app/data` y ejecutan una
inicialización idempotente antes de arrancar. No hay que ejecutar ningún CLI ni
instalar Python, Node o servicios systemd en la Raspberry.

El frontend se publica en el puerto `80`. La API solo se expone dentro de la
red Docker y el panel la consume mediante nginx.

Para actualizaciones automatizadas, `deploy/reconcile.sh` lee `deploy/release`,
descarga las imágenes y aplica la versión indicada.
