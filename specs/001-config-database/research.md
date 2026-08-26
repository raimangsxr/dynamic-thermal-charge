# Phase 0 — Research: Configuración y histórico en base de datos

**Feature**: `001-config-database` | **Fecha**: 2026-08-26

Todas las mediciones de esta sección se han tomado en la máquina de desarrollo
(Apple Silicon, Python 3.12) con SQLAlchemy 2.0.52 y Alembic 1.19.1 instalados en un
entorno virtual limpio. La Raspberry Pi 2B (Cortex-A7 a 900 MHz) es aproximadamente un
orden de magnitud más lenta por núcleo, por lo que los tiempos de importación se
extrapolan multiplicando por 10-20; la memoria residente es comparable.

---

## D1 — SQLAlchemy Core, no ORM

**Decisión**: usar SQLAlchemy Core (`MetaData`, `Table`, `select`, `insert`) y funciones
explícitas de conversión fila → dataclass. NO usar el ORM declarativo ni `Session`.

**Rationale**:

- El dominio ya son `dataclass(frozen=True)` inmutables y el Principio VI las prefiere
  frente a objetos mutables con estado escondido. El ORM introduce exactamente eso: una
  `Session` con identity map, estado sucio y carga diferida.
- Con el ORM habría dos modelos (entidad mapeada mutable y dataclass inmutable) y una
  conversión entre ambos. Con Core hay un solo modelo y una función de conversión, que es
  además el punto natural donde aplicar la validación íntegra del Principio III.
- Coste medido de importación (acumulado, 3 ejecuciones):

  | Import | Tiempo (µs) | RSS tras importar |
  | --- | ---: | ---: |
  | intérprete base | — | 9 MB |
  | `import yaml` (situación actual) | 20 700 – 30 600 | — |
  | `import sqlalchemy` (Core) | 155 834 – 159 017 | 36 MB |
  | `import sqlalchemy.orm` | 190 936 – 211 577 | 42 MB |
  | `import alembic.config` | 224 064 | — |

  El ORM añade ~40 ms y ~6 MB sobre Core. Es poco, pero es coste sin contrapartida: no
  necesitamos ninguna de sus prestaciones.

**Alternativas descartadas**:

- **ORM declarativo**: la comodidad de las relaciones no compensa introducir estado mutable
  en el borde de datos ni duplicar el modelo de dominio.
- **`sqlite3` + `pg8000` en crudo**: obligaría a mantener y probar dos dialectos de SQL a
  mano. Descartado ya en la conversación con el usuario.

---

## D2 — Driver de PostgreSQL: `pg8000`, no `psycopg`

**Decisión**: la URL de PostgreSQL soportada es `postgresql+pg8000://`. `pg8000` es el
driver declarado en el extra opcional.

**Rationale**: **no existe ninguna wheel `linux_armv7l` en PyPI para ninguno de los
candidatos**. Consultado el índice de PyPI:

| Paquete | Versión | Wheel pura (`py3-none-any`) | Wheel `armv7l` | Necesita compilar en la Pi |
| --- | --- | :---: | :---: | :---: |
| `pg8000` | 1.31.5 | sí | no | **no** |
| `psycopg` (v3) | 3.3.4 | sí | no | no, pero necesita `libpq5` del sistema |
| `psycopg2-binary` | 2.9.12 | no | no | **sí** (`gcc`, `libpq-dev`) |
| `greenlet` | 3.5.5 | no | no | **sí** |
| `SQLAlchemy` | 2.0.52 | sí | no | no (cae a la wheel pura, más lenta) |
| `Alembic` | 1.19.1 | sí | no | no |

`pg8000` es Python puro y no depende de `libpq`: se instala en la Pi 2B sin compilador ni
paquetes de sistema, y sin depender de que el `libpq5` del sistema sea compatible. Su
dialecto viene integrado en SQLAlchemy (`sqlalchemy/dialects/postgresql/pg8000.py`),
verificado en la versión instalada.

Su desventaja —menor rendimiento que `psycopg2` en cargas intensivas— es irrelevante aquí:
el perfil de acceso es una lectura de configuración por refresco de plan y unas pocas
inserciones de auditoría por noche.

**Alternativas descartadas**:

- **`psycopg` v3 sin extra binario**: viable, pero añade una dependencia del `libpq5` del
  sistema y de su versión. Más piezas que pueden romper una actualización de la Pi.
- **`psycopg2` del repositorio de la distribución** (`apt install python3-psycopg2`): rompe
  el aislamiento del entorno virtual del despliegue.

---

## D3 — `greenlet` no es necesario

**Decisión**: usar exclusivamente la API síncrona de SQLAlchemy. No declarar el extra
`asyncio`.

**Rationale**: verificado que `pip install 'sqlalchemy>=2' alembic` en un entorno limpio
instala únicamente `SQLAlchemy`, `typing_extensions`, `Mako` y `MarkupSafe`. **No arrastra
`greenlet`**, que es el único de los candidatos que exigiría un compilador en la Pi.
Cualquier uso de la API asíncrona lo reintroduciría, así que queda prohibido en esta
feature.

**Huella total de dependencias nuevas**: `SQLAlchemy`, `typing_extensions` (runtime);
`Alembic`, `Mako`, `MarkupSafe` (solo migraciones); `pg8000` (solo PostgreSQL).

---

## D4 — Alembic fuera de la ruta de importación del runtime

**Decisión**: `alembic` se importa únicamente dentro de las operaciones de inicialización y
migración (`dtc db init`, `dtc db upgrade`). El arranque del servicio NO importa Alembic;
comprueba la versión del esquema leyendo la tabla `alembic_version` con Core.

**Rationale**: `import alembic.config` cuesta 224 ms en la máquina de desarrollo, del orden
de 2-4 s en la Pi. Es coste inútil en un proceso que arranca para correr meses. Además
mantiene `Mako` y `MarkupSafe` fuera de la ruta crítica.

---

## D5 — Verificación de versión de esquema sin Alembic

**Decisión**: el servicio embarca la revisión de esquema que comprende como constante. Al
arrancar lee `alembic_version.version_num` de la base de datos y compara:

| Estado | Acción |
| --- | --- |
| tabla ausente | error accionable: «base de datos no inicializada, ejecuta `dtc db init`» |
| revisión igual a la esperada | continúa |
| revisión conocida y anterior | error accionable: «migración pendiente, ejecuta `dtc db upgrade`» |
| revisión desconocida para el servicio | **rechaza el arranque** (FR-010, Principio III) |

**Rationale**: una revisión que el servicio no conoce solo puede venir de un binario más
nuevo que ya migró la base de datos. Operar sobre ella significaría interpretar columnas que
no comprende para decidir qué relé cerrar. El Principio I resuelve la ambigüedad hacia el
estado seguro: no arrancar. La lista de revisiones conocidas se deriva del directorio de
migraciones en tiempo de construcción, no en tiempo de arranque.

---

## D6 — PRAGMAs de SQLite: hay que fijarlos explícitamente

**Decisión**: registrar un listener `connect` en el engine de SQLite que ejecute en cada
conexión nueva:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;
```

**Rationale**: medido sobre una base de datos SQLite recién creada con Python 3.12 y SQLite
3.45.3, los valores por defecto son:

| PRAGMA | Por defecto | Problema |
| --- | --- | --- |
| `foreign_keys` | **`0` (OFF)** | las claves ajenas del modelo **no se aplicarían**: se podría borrar una instalación dejando acumuladores huérfanos, o insertar un intervalo de plan apuntando a un acumulador inexistente |
| `journal_mode` | `delete` | sin WAL, un lector bloquea al escritor; con el controlador leyendo y el CLI editando, el segundo proceso choca |
| `synchronous` | `2` (FULL) | correcto por defecto, pero se fija de forma explícita porque WAL lo relaja a `NORMAL` en algunas configuraciones y el Principio IV exige durabilidad |
| `busy_timeout` | `5000` ms | correcto, se fija explícitamente para no depender del valor por defecto del driver |

`foreign_keys = OFF` por defecto es la trampa importante: sin este listener, la mitad de las
garantías de integridad del modelo de datos serían decorativas.

---

## D7 — El plan activo sigue teniendo una copia local en disco

**Decisión**: mantener `PlanStore` sobre fichero JSON local como **caché de reanudación**
del plan activo, y registrar además cada plan en la base de datos como histórico auditable.
La base de datos es la fuente de verdad de la configuración y del histórico; el fichero
local es la fuente de reanudación del plan en curso.

**Rationale**: es la única decisión de este plan que se aparta de la lectura literal del
enunciado, y lo hace para no perder una garantía existente. Con PostgreSQL remoto y la
red caída en el arranque, un diseño que guardase el plan activo únicamente en la base de
datos no tendría plan que reanudar y dejaría todas las salidas apagadas. Eso es seguro
(Principio I) pero es una regresión de continuidad frente al comportamiento actual
(Principio IV): hoy la Pi reanuda su plan tras un reinicio sin depender de nada externo.

Con la copia local, el peor caso pasa de «noche sin calefacción por un corte de red» a
«noche ejecutando el último plan conocido, con degradación registrada». La escritura del
fichero ya es atómica y durable (`tempfile` + `fsync` + `os.replace`) y está cubierta por
tests; no hay que rehacerla.

Consecuencia: `runtime.state_file` sobrevive como parámetro de configuración, ahora leído de
la base de datos.

**Alternativa descartada**: plan activo solo en base de datos. Más limpio conceptualmente,
peor en el modo de fallo que justamente introduce esta feature.

---

## D8 — Instantes: UTC en la frontera, siempre

**Decisión**: toda columna temporal se almacena como instante en UTC. La conversión a UTC
ocurre al escribir y la reconstrucción como `datetime` consciente de zona ocurre al leer,
en el borde de persistencia. Ninguna capa superior ve un `datetime` ingenuo procedente de la
base de datos.

**Rationale**: SQLite no tiene tipo temporal nativo y descarta la información de zona;
PostgreSQL sí la conserva. Sin una regla única, el mismo código daría resultados distintos
según el motor y FR-002 (comportamiento idéntico) sería imposible de cumplir. Los horarios
de la configuración (`start_time`, `end_time`) siguen siendo horas locales de la zona
configurada y se almacenan como texto `HH:MM`, no como instantes: son reglas, no momentos.

---

## D9 — Edición concurrente: bloqueo optimista por revisión

**Decisión**: la tabla de instalación lleva una columna `revision` entera. Cada edición lee
la revisión, valida la configuración completa resultante y escribe con
`WHERE revision = <leída>`, incrementándola. Si la actualización afecta a cero filas, la
edición se rechaza indicando que la configuración cambió mientras se editaba.

**Rationale**: FR-040 exige que dos ediciones concurrentes no pierdan silenciosamente una de
las dos. Un bloqueo optimista sobre un contador es la solución más simple que funciona
igual en ambos motores, no requiere bloqueos explícitos y no puede dejar la base de datos
bloqueada si un proceso muere. La validación de FR-034 se hace sobre la configuración
completa resultante dentro de la misma transacción, lo que hace imposible aplicar un cambio
parcialmente válido.

---

## D10 — Retención: acotada y ejecutada en el refresco de plan

**Decisión**: retención configurable en días, valor por defecto **365**, `null` para
ilimitada. La limpieza se ejecuta al inicializar y después de cada refresco de plan, no en
un temporizador propio.

**Rationale**: dimensionado del histórico para la instalación de referencia del repositorio
(4 acumuladores, intervalo de 30 min, ventana de 8 h, un plan por noche):

| Tabla | Filas por noche | Filas al año |
| --- | ---: | ---: |
| `plan` | 1 | 365 |
| `plan_slot` (16 intervalos × hasta 4 acumuladores) | ≤ 64 | ≤ 23 360 |
| `forecast` | 1 | 365 |
| `output_transition` (2 por acumulador) | ~8 | ~2 920 |
| `config_change` (auditoría de ediciones) | ~0 | decenas |
| **Total** | **~75** | **~27 000** |

Del orden de unos pocos megabytes al año: irrelevante para la tarjeta de la Pi. El riesgo
real no es el volumen esperado sino el descontrolado (un bucle de refresco mal configurado),
y para eso basta la retención por defecto. Añadir un temporizador dedicado sería complejidad
sin necesidad (YAGNI, Principio VI).

---

## D11 — Registro del origen de la configuración sin filtrar credenciales

**Decisión**: al arrancar se registra el nombre del motor, el modo (local o remoto) y el
nombre de la base de datos y del host cuando aplique. **Nunca** se registra la URL
completa, ni siquiera enmascarada.

**Rationale**: SQLAlchemy ofrece `URL.render_as_string(hide_password=True)`, verificado:
`postgresql+pg8000://user:secreto@host:5432/dtc` se renderiza como
`postgresql+pg8000://user:***@host:5432/dtc`. Es útil, pero solo enmascara la contraseña:
el usuario y el host siguen apareciendo. Para el propósito de FR-005 —distinguir local de
remoto— basta con el motor, el host y el nombre de la base de datos, así que se construye el
mensaje campo a campo en lugar de renderizar la URL. Es la opción que no puede filtrar un
componente nuevo si mañana se añade un parámetro a la URL.

Un motor distinto de `sqlite` o `postgresql` se rechaza al arrancar enumerando los
admitidos (FR-004).

---

## D12 — Estrategia de tests sin PostgreSQL

**Decisión**: tres niveles.

1. **Unitarios del núcleo**: repositorio de configuración falso que implementa el `Protocol`.
   El planificador y el modelo térmico no ven la base de datos. Sin dependencia de
   SQLAlchemy.
2. **Integración sobre SQLite**: base de datos en fichero temporal (`tmp_path`), no en
   memoria, para poder ejercitar de verdad WAL, las claves ajenas y las migraciones. Cubren
   el esquema, la semilla, la validación, la edición, el bloqueo optimista y la retención.
3. **Compatibilidad con PostgreSQL**: suite marcada que se **omite por defecto** y solo se
   ejecuta si está definida `DTC_TEST_POSTGRES_URL`. Nunca se ejecuta en la suite normal ni
   en la Pi.

Los caminos de fallo (base de datos ausente, inalcanzable, esquema desconocido, caída en
caliente, fallo de escritura de histórico) se prueban inyectando un repositorio que lanza el
error de dominio correspondiente, con reloj y `wait` controlados. Ninguno duerme en tiempo
real (Principio V).

**Riesgo asumido y su mitigación**: un bug específico del dialecto de PostgreSQL podría no
detectarse en la suite por defecto. Mitigación: restringir el SQL al subconjunto portable
que genera Core, prohibir tipos y funciones específicas de un motor en el esquema, y dejar
la suite de compatibilidad disponible para ejecutarla a mano contra un PostgreSQL real antes
de un despliegue que lo use.

---

## D13 — Presupuesto de arranque en la Raspberry Pi 2B

**Decisión**: importación perezosa del subpaquete de persistencia, de modo que
`--help` y cualquier ruta que no toque la base de datos no paguen el coste. Presupuesto
declarado y verificable en el despliegue:

- Tiempo añadido al arranque: **< 5 s** en la Pi 2B (extrapolado de 157 ms medidos × 20,
  con margen).
- Memoria residente del proceso de servicio: **< 80 MB** (medido: 36 MB con Core importado
  sobre 9 MB de base; el resto es margen para el pool de conexiones y los datos).

Sobre 1 GB de RAM, ~4 % de memoria. El arranque es un coste que se paga una vez cada varios
meses. Si la medición en la Pi excediera el presupuesto, la vía de escape es reducir el
esquema importado, no volver a SQL en crudo.

**Alternativa descartada**: precargar el esquema con `pickle` o generar código. Complejidad
desproporcionada para 3 s de arranque.
