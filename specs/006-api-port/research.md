# Research: Cambiar puerto del API

- **Decision**: Usar 8080 como valor predeterminado en `api.settings` y reflejarlo en proxies, nginx, ejemplos, README y pruebas.
- **Rationale**: Es la única fuente de configuración predeterminada; `DTC_API_PORT` y `--port` ya permiten sobrescritura.
- **Alternatives considered**: Cambiar solo el valor Python; descartado porque dejaría proxies, despliegue y documentación inconsistentes.
