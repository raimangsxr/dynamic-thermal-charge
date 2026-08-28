## Why

El panel web no se distribuye actualmente como un artefacto versionado y consumible por el repositorio de despliegue. Automatizar su publicación al crear una release mantiene el binario del frontend, su integridad y la configuración de despliegue alineados con el código etiquetado.

## What Changes

- Añadir un workflow de GitHub Actions que se ejecute al publicar una release del repositorio.
- Construir el frontend Angular y publicar un `frontend.tar.gz` en la release, con los recursos servibles en la raíz del archivo.
- Calcular y conservar el SHA-256 del artefacto publicado.
- Actualizar `group_vars/all.yml` en `raimangsxr/dynamic-thermal-charge-deploy` con el commit etiquetado, la versión de la release, la URL pública del artefacto y su checksum.

## Capabilities

### New Capabilities

- `frontend-release-publication`: publicación reproducible del frontend versionado y sincronización de sus metadatos con la configuración de despliegue.

### Modified Capabilities

- Ninguna.

## Impact

- Nuevo workflow en `.github/workflows/` y secreto de Actions con permiso de escritura sobre el repositorio de despliegue.
- Build de Angular en `frontend/` y archivo publicado en las releases de GitHub.
- Repositorio externo `raimangsxr/dynamic-thermal-charge-deploy`, fichero `group_vars/all.yml`.
