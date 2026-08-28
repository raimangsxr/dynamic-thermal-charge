## 1. Configuración del workflow de release

- [x] 1.1 Crear `.github/workflows/publish-frontend-release.yml` para el evento `release.published`, con permisos mínimos, concurrencia para el inventario de despliegue y checkout del tag; verificar que el YAML es válido y que el SHA resuelto para un tag anotado es el commit completo etiquetado.
- [x] 1.2 Configurar el job de build con la versión de Node declarada por el proyecto, `npm ci` y el build de producción en `frontend/`; verificar que genera los ficheros estáticos esperados en `frontend/dist/panel/browser/`.
- [x] 1.3 Empaquetar el contenido de `frontend/dist/panel/browser` como `frontend.tar.gz`, calcular su SHA-256 y exponer commit, versión, URL del asset y checksum entre jobs; verificar con `tar -tzf` que `index.html` y los bundles están en la raíz y no bajo `browser/`.
- [ ] 1.4 Adjuntar o reemplazar `frontend.tar.gz` en la release que activó el workflow; verificar mediante GitHub CLI/API que existe un único asset con ese nombre y que su descarga coincide con el SHA-256 calculado.

## 2. Sincronización con el repositorio de despliegue

- [x] 2.1 Documentar y consumir el secreto `DEPLOY_REPOSITORY_TOKEN`, y determinar/configurar la rama destino de `raimangsxr/dynamic-thermal-charge-deploy`; verificar que el workflow falla antes de un push si el secreto no permite escritura.
- [ ] 2.2 Añadir el job dependiente que hace checkout del repositorio de despliegue y actualiza exclusivamente `application.ref`, `application.frontend.version`, `application.frontend.url` y `application.frontend.sha256` en `group_vars/all.yml`; verificar que un YAML de ejemplo conserva los demás campos y recibe los cuatro valores correctos.
- [ ] 2.3 Confirmar y hacer push solo cuando `group_vars/all.yml` cambie, identificando la release en el mensaje de commit; verificar que una reejecución sin cambios no crea un commit vacío.

## 3. Validación de extremo a extremo

- [ ] 3.1 Ejecutar o revisar una release de prueba y verificar que el asset público, su checksum, el SHA del commit etiquetado y la versión coinciden con los cuatro valores confirmados en el repositorio de despliegue.
- [x] 3.2 Ejecutar `openspec validate publish-frontend-release-artifact --strict` y las comprobaciones de formato/lint disponibles para el workflow; verificar que finalizan correctamente.
