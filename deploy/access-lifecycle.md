# Ciclo de acceso administrativo

El despliegue oficial tiene un único aprovisionamiento: `DTC_API_TOKEN` debe
estar definido en el entorno del backend antes del primer arranque. Debe ser un
valor real de al menos 32 caracteres; los valores de ejemplo se rechazan. El
arranque almacena únicamente su digest no reversible en la configuración
persistente y no crea credenciales temporales.

Si falta `DTC_API_TOKEN`, es débil o la instalación no contiene un digest
administrativo, el servicio termina con un error accionable. No existe un modo
parcial de onboarding, ni rutas `/api/v1/onboarding`, ni una pantalla de
configuración inicial. Las columnas históricas de onboarding se conservan solo
para poder abrir instalaciones antiguas sin una migración destructiva; el
código actual no las utiliza como mecanismo de acceso.

El panel valida la credencial contra la API antes de guardarla. Una credencial
rechazada no se escribe en `sessionStorage`, no aparece en la URL ni se muestra
en el mensaje de error. La credencial aceptada se limita a la pestaña mediante
`sessionStorage`. Si una petición autenticada recibe `401`, el panel borra la
sesión, redirige una sola vez a login y muestra que la sesión ya no es válida.
El cierre voluntario borra la sesión sin mostrar ese mensaje.

La rotación sigue haciéndose desde la configuración administrativa existente,
editando el secreto `admin_token_digest` con un nuevo token. La sesión anterior
queda invalidada; el operador debe volver a introducir el nuevo valor en el
panel.

Para comprobar el ciclo completo en desarrollo:

```sh
export DTC_API_TOKEN="un-token-aleatorio-de-al-menos-32-caracteres"
make compose-dev
make check
```

La documentación operativa general del repositorio debe enlazar esta guía al
integrar el cambio en el README raíz.
