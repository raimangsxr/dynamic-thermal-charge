## Context

El frontend Angular se construye desde `frontend/`; su configuración actual genera los ficheros servibles bajo `dist/panel/browser/`. No existe todavía un directorio `.github/workflows/`. El workflow debe publicar el binario de una release ya creada y actualizar un segundo repositorio privado o externo, para el que el `GITHUB_TOKEN` del repositorio origen no tiene permisos de escritura.

## Goals / Non-Goals

**Goals:**

- Asociar de manera determinista el build y `application.ref` al commit efectivo del tag, incluidos los tags anotados.
- Producir un único archivo portable, con el contenido de `dist/panel/browser` en su raíz, y publicar su SHA-256.
- Actualizar de forma atómica los cuatro campos de frontend y aplicación del inventario de despliegue mediante un commit automatizado.

**Non-Goals:**

- Construir, publicar o desplegar artefactos de backend.
- Crear releases o tags; el workflow solo reacciona a una release publicada.
- Desplegar directamente en hosts ni modificar playbooks de Ansible.

## Decisions

### Evento y resolución del código de la release

El workflow se disparará con `release.types: [published]`, hará checkout del tag de `github.event.release.tag_name` con historial suficiente y resolverá el commit mediante Git (dereferenciando un tag anotado). El nombre del tag se usará como versión y para construir la URL canónica del asset.

Usar `github.sha` o `target_commitish` se descarta: en releases y tags anotados puede no expresar inequívocamente el commit de la etiqueta.

### Empaquetado y publicación verificable

Se ejecutará `npm ci` y el script de producción del frontend. El workflow archivará el contenido de `frontend/dist/panel/browser` usando ese directorio como raíz de `tar`, calculará `sha256sum` sobre el `.tar.gz` y lo subirá con GitHub CLI o una acción de release que permita reemplazar el asset por nombre al reintentar.

Archivar `dist/panel` completo se descarta porque la configuración Angular actual introduce el directorio `browser/`, incompatibile con la estructura solicitada al extraer el asset.

### Actualización del repositorio de despliegue

Un segundo job, dependiente de la publicación del asset, realizará checkout de `raimangsxr/dynamic-thermal-charge-deploy` en su rama principal configurada. Usará un token almacenado como secreto (propuesto: `DEPLOY_REPOSITORY_TOKEN`) con permiso de contenido de escritura, actualizará exclusivamente los cuatro valores YAML mediante una herramienta que preserve el resto del fichero y confirmará/push del cambio con un mensaje que identifique la release.

El token por defecto de Actions se descarta porque no autoriza escritura entre repositorios. Abrir una pull request se descarta como comportamiento por defecto porque el requisito solicita que el fichero quede escrito tras la release; podrá reconsiderarse si la gobernanza del repositorio exige revisión.

### Integridad y orden de operaciones

El SHA-256 y la URL se calcularán antes de modificar el repositorio de despliegue. El segundo job solo se ejecutará si la subida del asset termina correctamente. Así, el inventario no podrá referir a un artefacto inexistente y el checksum documentado corresponde a los bytes publicados.

## Risks / Trade-offs

- [El secreto no está definido, está caducado o no permite push] → Documentar el secreto requerido y hacer que el job falle antes de confirmar cambios remotos.
- [Una release se vuelve a ejecutar] → Reemplazar el asset del mismo nombre y aplicar los valores de nuevo; si no hay diff YAML, no crear un commit vacío.
- [Una ejecución simultánea para el mismo destino] → Usar un grupo de concurrencia del workflow para serializar actualizaciones del inventario de despliegue.
- [El tag contiene caracteres que requieren codificación en una URL] → Construir la URL con la URL del asset devuelta por GitHub o codificar el tag antes de escribir YAML.

## Migration Plan

1. Configurar `DEPLOY_REPOSITORY_TOKEN` en los secretos del repositorio origen, con acceso mínimo de escritura a `dynamic-thermal-charge-deploy`.
2. Integrar el workflow y publicar una release de prueba.
3. Verificar el asset descargado, su estructura y los cuatro valores confirmados en el repositorio de despliegue.
4. Para revertir una publicación, restaurar el commit del inventario de despliegue y volver a publicar/reemplazar el asset de la release corregida.
