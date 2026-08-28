## Purpose

Publicar cada versión liberada del panel como un artefacto verificable y dejar al repositorio de despliegue preparado para instalar exactamente esa versión.

## ADDED Requirements

### Requirement: Publicación del artefacto del frontend al crear una release
El sistema SHALL ejecutar una automatización cuando una release sea publicada en `raimangsxr/dynamic-thermal-charge`. La automatización MUST construir el frontend que corresponde al tag de la release y adjuntar un único archivo `frontend.tar.gz` a esa misma release.

#### Scenario: Release publicada correctamente
- **WHEN** se publica una release con un tag que apunta a un commit del repositorio
- **THEN** la release contiene el asset descargable `frontend.tar.gz` construido desde ese commit

#### Scenario: Nueva ejecución para la misma release
- **WHEN** la automatización vuelve a ejecutarse para una release que ya tiene un asset llamado `frontend.tar.gz`
- **THEN** el asset existente se sustituye por el artefacto recién generado sin crear archivos duplicados

### Requirement: Contenido instalable del archivo del frontend
El archivo `frontend.tar.gz` SHALL contener en su raíz los ficheros estáticos generados que el servidor web debe servir, incluidos `index.html` y los bundles de la aplicación. El archivo MUST NOT añadir un directorio contenedor como `browser/`, `panel/` o `dist/` antes de dichos ficheros.

#### Scenario: Extracción del archivo para servir el panel
- **WHEN** se extrae `frontend.tar.gz` en el directorio público del servidor web
- **THEN** `index.html` y los assets del build quedan directamente en ese directorio

### Requirement: Sincronización de metadatos de despliegue
Después de publicar el artefacto, el sistema SHALL actualizar `group_vars/all.yml` del repositorio `raimangsxr/dynamic-thermal-charge-deploy` para que `application.ref` sea el SHA completo del commit al que resuelve el tag, `application.frontend.version` sea el tag de la release, `application.frontend.url` sea la URL pública del asset publicado y `application.frontend.sha256` sea el SHA-256 del contenido exacto de ese asset. La actualización MUST ser confirmada en la rama de despliegue configurada.

#### Scenario: Metadatos de una release actualizados
- **WHEN** `frontend.tar.gz` se ha adjuntado correctamente a una release `1.1.0` basada en el commit `ef2f9ef818fb61d0394780baab8fdef1f6358e1f`
- **THEN** el fichero de despliegue contiene ese SHA en `application.ref`, `1.1.0` en `application.frontend.version`, la URL pública del asset en `application.frontend.url` y su checksum en `application.frontend.sha256`

#### Scenario: Credenciales de despliegue no disponibles
- **WHEN** la automatización no dispone de credenciales con permiso para escribir en el repositorio de despliegue
- **THEN** falla sin confirmar una actualización parcial de `group_vars/all.yml`
