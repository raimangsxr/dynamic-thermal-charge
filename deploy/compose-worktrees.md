# Compose aislado por checkout

Los comandos de desarrollo calculan un nombre de proyecto Docker Compose a
partir de la ruta física del checkout. El nombre incluye un prefijo legible y
un hash de esa ruta, por lo que dos worktrees distintos no comparten
contenedores, redes ni volúmenes. Repetir el comando en el mismo checkout
reutiliza el mismo proyecto.

SQLite y PostgreSQL usan exactamente el mismo nombre para una ruta dada:

```sh
make compose-dev
make compose-dev-postgres
```

Las operaciones de parada y limpieza también están acotadas al proyecto del
checkout actual:

```sh
make compose-down
make compose-clean
make compose-down-postgres
make compose-clean-postgres
```

Para automatización se puede fijar explícitamente un nombre válido para
Compose:

```sh
COMPOSE_PROJECT_NAME=ci-dtc-42 make compose-check
```

El Compose de producción no usa este cálculo: conserva sus nombres de servicio
y sus rutas persistentes explícitas.
