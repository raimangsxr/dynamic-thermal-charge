# Activación de la puerta de calidad

Status: approved

## Goal

El arnés de calidad `.ai-standard` está instalado con los perfiles
`python-fastapi` y `angular`, pero el `Makefile` raíz nunca lo incluye y
`AI_STANDARD_EXPOSE_TARGETS` está vacío, así que no se ejecuta nunca. `make lint`
es `compileall`, `make check` ignora el frontend por completo y CI compila el
panel sin ejecutar sus 205 tests: hoy ninguno de ellos puede romper la build.

## Requirements

- R1: `make setup`, `make dev`, `make test`, `make lint` y `make check` seguirán
  siendo el contrato de comandos, ahora resueltos por el arnés `.ai-standard`.
- R2: `make test` ejecutará las pruebas de backend y de frontend. `make check`
  ejecutará además el linter, el build del panel, la comprobación del grafo de
  migraciones y la validación de los ficheros Compose que ya cubre hoy.
- R3: `ruff check` estará configurado en `backend/pyproject.toml` y no reportará
  ningún hallazgo. Los patrones deliberados del proyecto (imports locales de
  dependencias opcionales) se resolverán con exclusiones justificadas por regla y
  fichero, nunca silenciando la regla globalmente.
- R4: CI ejecutará el mismo `make check` que un desarrollador, de modo que un
  test de frontend en rojo o un hallazgo de linter impedirán mezclar.
- R5: La suite medirá cobertura y publicará el porcentaje total. No se impondrá
  umbral en esta tanda.
- R6: Las advertencias de la propia base de código serán errores en la suite. Las
  deprecaciones de terceros conocidas se silenciarán una por una, con su motivo.
- R7: No se aplicará reformateo automático ni comprobación de tipos en esta
  tanda, y no se añadirán dependencias al frontend.

## Outcome

`make check` ejecuta backend (799 pruebas, cobertura total 83 %), frontend (205
pruebas), `ruff`, el build del panel y la validación de los tres ficheros
Compose, y CI invoca `make setup` y `make check` en lugar de su propia lista de
pasos. Verificado que falla: un hallazgo de `ruff` y un test de frontend en rojo
devuelven salida distinta de cero, algo que antes era imposible.

Sin spec viva: es contrato de herramientas de desarrollo, no comportamiento de
producto, y su fuente de verdad son el `Makefile` y `.ai-standard/project.mk`.

Tres cosas que la activación destapó y que el contrato no había previsto:

- El script del arnés ejecuta `ruff format --check` en cuanto detecta ruff
  configurado, lo que contradice R7. Resuelto con `AI_LINT_CMD`, la vía de
  escape de `project.mk`, con una nota para retirarla cuando se adopte el
  formateador.
- `ruff` quedó fijado a una versión exacta y las reglas declaradas
  explícitamente: el venv limpio instaló 0.16.6 frente a 0.15.2 del entorno de
  desarrollo, con reglas por defecto distintas, de modo que el rango habría
  hecho fallar CI con un cambio que pasa en local.
- `filterwarnings` como error es sensible al entorno: en un venv limpio
  `starlette.testclient` dispara una deprecación de `anyio` que el entorno de
  desarrollo no mostraba. Silenciada con su motivo.

La cláusula de R2 sobre el grafo de migraciones se cumple por la suite, no por
el arnés: `upgrade_to_head()` llama a `head_revision()` en cada inicialización y
`get_current_head` lanza `MultipleHeads`. El paso de Alembic del arnés queda
inerte porque el proyecto renuncia deliberadamente a `alembic.ini`, y no se ha
añadido uno para contentar a la herramienta.

La suite pasa de ~70 s a ~105 s por la instrumentación de cobertura, y
`make check` suma el build del panel.
