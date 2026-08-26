# Contract — Servidor web del dispositivo

**Feature**: `003-web-panel`

nginx sirve el panel y hace de intermediario hacia la API. De esa combinación salen dos
propiedades que valen más que la comodidad: el navegador ve **un único origen**, y la API **no
necesita exponerse en la red**.

## Sitio

```nginx
server {
    listen 80;
    server_name _;

    root /var/www/dynamic-thermal-charge;
    index index.html;

    # 1. Recarga de rutas internas del panel (FR-040).
    #    Sin esto, recargar una dirección interna devuelve 404: en el disco no
    #    existe ese fichero, solo index.html y el enrutador del panel.
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 2. Caché derivada del nombre del fichero (FR-041, research D5).
    #    La compilación pone una huella en el nombre de cada recurso cuyo
    #    contenido puede cambiar, así que son inmutables por construcción.
    location ~* \.(js|css|woff2?|svg|png|jpg|ico)$ {
        expires 1y;
        add_header Cache-Control "public, max-age=31536000, immutable";
        try_files $uri =404;
    }

    #    index.html NO se cachea. Es el punto de entrada que apunta a los
    #    recursos con huella, y cachearlo es exactamente el fallo que hace que
    #    el operador actualice, recargue y siga viendo la interfaz antigua.
    location = /index.html {
        add_header Cache-Control "no-cache";
    }

    # 3. La API, en la interfaz local del propio dispositivo (FR-039).
    location /api/ {
        proxy_pass http://127.0.0.1:8420;
        proxy_http_version 1.1;
        # La cabecera de autorización debe llegar íntegra. nginx no la elimina,
        # pero declararlo evita que un cambio futuro la rompa en silencio.
        proxy_set_header Authorization $http_authorization;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 30s;
    }

    # La comprobación de salud de la API, para un monitor externo.
    location = /health {
        proxy_pass http://127.0.0.1:8420/health;
    }

    # La descripción de la API exige credencial, igual que todo lo demás.
    location = /docs { proxy_pass http://127.0.0.1:8420/docs; }
    location = /openapi.json { proxy_pass http://127.0.0.1:8420/openapi.json; }
}

# ---------------------------------------------------------------------------
# Cifrado en tránsito. Deliberadamente COMENTADO: no se activa en esta fase,
# pero es la vía que la fase anterior dejó como riesgo asumido, y está aquí para
# que quien la necesite no tenga que inventarla.
#
# Sin esto, el panel y la API sirven en claro: cualquiera en la red puede leer la
# credencial al pasar, y quien la tenga puede cambiar la potencia máxima y la
# asignación de pines. Aceptable en una red doméstica de confianza; no aceptable
# expuesto a internet.
#
# server {
#     listen 443 ssl;
#     server_name pi.example.lan;
#     ssl_certificate     /etc/ssl/certs/dtc.crt;
#     ssl_certificate_key /etc/ssl/private/dtc.key;
#     # ... el mismo contenido que el bloque de arriba ...
# }
#
# server {
#     listen 80;
#     server_name pi.example.lan;
#     return 301 https://$host$request_uri;
# }
# ---------------------------------------------------------------------------
```

## Invariantes que la configuración debe cumplir

| Invariante | Por qué |
| --- | --- |
| `try_files ... /index.html` en `/` | FR-040: recargar una ruta interna no puede dar 404 |
| `index.html` con `no-cache` | FR-041: sin esto, una versión nueva no se recoge |
| recursos con huella como `immutable` | son inmutables por construcción; cachearlos es gratis |
| `proxy_pass` a `127.0.0.1` | FR-039: la API nunca se expone en la red |
| la cabecera de autorización se propaga | sin ella, todo devolvería 401 |
| el bloque de cifrado presente y comentado | FR-042: la vía documentada, no activada |

## Lo que nginx NO hace

- **No** guarda ni conoce la credencial de la API. Solo la reenvía.
- **No** sirve la base de datos ni ningún fichero de `/var/lib`.
- **No** se instala ni se habilita automáticamente: el instalador deja la configuración disponible
  y lo dice (FR-043).
