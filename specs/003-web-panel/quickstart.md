# Quickstart — Panel web

**Feature**: `003-web-panel`

## Requisitos de la máquina de desarrollo

Node **≥ 22.22.3**, o ≥ 24.15, o ≥ 26. Angular 22 no funciona con versiones anteriores.

```bash
node --version    # v24.18.0 en la máquina donde se desarrolló esta fase
```

**En la Raspberry Pi no hace falta Node.** El panel se compila aquí y se copian 256 kB de
ficheros. Un `npm install` en un Cortex-A7 con 1 GB no termina, y la constitución lo prohíbe
explícitamente.

## Desarrollo local

Necesitas la API en marcha, que es la fase anterior:

```bash
# Terminal 1: la API
export DTC_DATABASE_URL="sqlite:///$(pwd)/var/dtc.db"
export DTC_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
dtc db upgrade && dtc api

# Terminal 2: el panel
cd frontend
npm install
npm start          # http://localhost:4200
```

En desarrollo, el servidor de Angular hace de intermediario hacia la API igual que nginx en el
dispositivo, así que **tampoco aquí hacen falta orígenes cruzados**. `DTC_API_CORS_ORIGINS` se
queda vacío, que es su valor por defecto.

El panel pedirá la credencial al abrirlo. Es el valor de `DTC_API_TOKEN`.

## Pruebas

```bash
cd frontend
npm test           # Vitest sobre jsdom: sin red, sin API real, sin navegador
```

Y la suite de Python sigue siendo la de siempre, sin cambios:

```bash
pytest
```

## Compilar para el dispositivo

```bash
cd frontend
npm run build      # produce frontend/dist/panel/browser/
du -sh dist        # ~256 kB para el andamiaje; presupuesto: < 500 kB en bruto
```

La compilación falla si el paquete supera el presupuesto declarado. Eso es deliberado: una
dependencia de gráficos añadida «solo para probar» debe fallar la compilación, no colarse.

## Desplegar en la Raspberry Pi

```bash
# 1. Compilar aquí, nunca allí
cd frontend && npm run build

# 2. Copiar los ficheros
rsync -a --delete dist/panel/browser/ pi:/tmp/panel/
ssh pi 'sudo install -d -o root -g root /var/www/dynamic-thermal-charge && \
        sudo rsync -a --delete /tmp/panel/ /var/www/dynamic-thermal-charge/'

# 3. Instalar nginx y la configuración del sitio (una sola vez)
ssh pi 'sudo apt-get install -y nginx'
ssh pi 'sudo install -m 0644 /opt/dynamic-thermal-charge/deploy/nginx/dynamic-thermal-charge.conf \
          /etc/nginx/sites-available/dynamic-thermal-charge'
ssh pi 'sudo ln -sf /etc/nginx/sites-available/dynamic-thermal-charge \
          /etc/nginx/sites-enabled/ && sudo rm -f /etc/nginx/sites-enabled/default'
ssh pi 'sudo nginx -t && sudo systemctl reload nginx'
```

O con el instalador, que deja la configuración disponible sin activarla:

```bash
sudo ./scripts/install-service.sh --with-api --with-panel
```

Después, el panel está en `http://<la-pi>/` y la API sigue escuchando **solo** en `127.0.0.1`.
nginx es el único componente expuesto en la red.

### Comprobar que la API no está expuesta

Merece la pena verificarlo una vez:

```bash
ssh pi 'ss -tlnp | grep 8080'     # debe mostrar 127.0.0.1:8080, no 0.0.0.0:8080
curl -s http://<la-pi>:8080/health   # debe fallar: la API no escucha ahí fuera
curl -s http://<la-pi>/health        # debe responder: nginx sí
```

## Añadir cifrado en tránsito

Sin cifrado, el panel y la API sirven en claro: cualquiera en tu red puede leer la credencial al
pasar, y quien la tenga puede cambiar la potencia máxima y la asignación de pines. **En una red
doméstica de confianza es razonable; expuesto a internet no lo es.**

La configuración del sitio lleva el bloque preparado y comentado. Para activarlo hacen falta un
certificado y su clave, descomentar el bloque y recargar nginx. La fase no lo activa por defecto
porque implica gestionar certificados, y esa decisión es del operador.

## Actualizar el panel

```bash
cd frontend && npm run build
rsync -a --delete dist/panel/browser/ pi:/tmp/panel/
ssh pi 'sudo rsync -a --delete /tmp/panel/ /var/www/dynamic-thermal-charge/'
```

**No hace falta recargar nginx ni borrar la caché del navegador.** Los recursos llevan una huella
en el nombre y `index.html` se sirve sin cachear, así que el navegador recoge la versión nueva al
recargar. Si alguna vez ves la interfaz antigua tras actualizar, lo primero que hay que revisar es
que `index.html` no esté siendo cacheado.

## Diagnóstico

| Síntoma | Causa probable |
| --- | --- |
| el panel pide la credencial una y otra vez | el token no coincide con `DTC_API_TOKEN`, o la API lo rotó |
| **404** al recargar una ruta interna del panel | falta `try_files ... /index.html` en la configuración de nginx |
| tras actualizar sigue apareciendo la interfaz antigua | `index.html` se está cacheando; debe ir con `no-cache` |
| **502** desde nginx | la API no está en marcha; `systemctl status dynamic-thermal-charge-api` |
| todo devuelve **401** a través de nginx pero funciona en local | nginx no está propagando la cabecera de autorización |
| el panel dice que el esquema necesita intervención | ejecuta `dtc db upgrade` **en el dispositivo**; el panel no puede hacerlo |
| avisa de que hay más de un controlador | revísalo: dos procesos conmutando los mismos relés es un riesgo eléctrico |
| aparece «estado no actual» de forma permanente | el controlador está parado o colgado; `systemctl status dynamic-thermal-charge` |
| el panel no refresca con la pestaña de fondo | correcto por diseño: se detiene para no cargar la Pi, y se reanuda al volver |
