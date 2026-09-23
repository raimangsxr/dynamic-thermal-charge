# Entrega reproducible

La imagen backend instala únicamente `backend/requirements.lock`, generado
con `uv pip compile` para una resolución universal de Python 3.12 y con hashes
de las distribuciones. El Dockerfile no instala ningún compilador: precarga el
`setuptools` fijado en `backend/build-requirements.lock` y usa
`--no-build-isolation`, de modo que las dependencias
que solo publican sdist deben poder construir su fallback Python puro dentro de
la imagen ARMv7.

Para actualizar dependencias de producción:

```sh
uv pip compile backend/pyproject.toml \
  --extra api --extra mqtt --extra gpio --extra db --extra postgres \
  --universal --python-version 3.12 --generate-hashes \
  --output-file backend/requirements.lock
make check
```

Las imágenes base se fijan por digest en ambos Dockerfiles. CBC se instala
desde Debian con versión exacta (`2.10.12+ds-1`) y el build deja la versión
efectiva en `/usr/share/dynamic-thermal-charge/cbc-package.txt` y en una label
OCI. El target `make delivery-check`, incluido en `make check`, valida que el
lock siga alineado con `pyproject.toml`, que las bases estén fijadas y que la
publicación conserve la cobertura ARMv7.

La publicación calcula el hash de cada lock, lo incluye como metadata OCI y
activa attestations de provenance y SBOM para cada imagen. La actualización de
una base, dependencia o versión de CBC debe ser deliberada y pasar de nuevo el
quality gate.
