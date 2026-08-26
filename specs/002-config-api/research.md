# Phase 0 — Research: API HTTP de estado y configuración

**Feature**: `002-config-api` | **Fecha**: 2026-08-26

Mediciones tomadas en la máquina de desarrollo (Apple Silicon, Python 3.12) sobre un entorno
virtual limpio con FastAPI 0.141.1, Starlette 1.6.0, Uvicorn 0.52.4, Pydantic 2.13.4 y
SQLAlchemy 2.0.52. La Raspberry Pi 2B es del orden de diez a veinte veces más lenta por
núcleo; la memoria residente es comparable.

---

## D1 — La pila entra en ARMv7, pero solo sin `uvicorn[standard]`

**Decisión**: dependencias del extra `api`: `fastapi`, `uvicorn` **pelado** y
`python-multipart` si hace falta. **PROHIBIDO `uvicorn[standard]`**.

**Rationale**: consultado el índice de PyPI, la disponibilidad de wheels `linux_armv7l` es la
que decide qué se puede instalar en la Pi sin compilador:

| Paquete | Wheel pura | Wheel `armv7l` | ¿Compilar en la Pi? |
| --- | :---: | :---: | :---: |
| `fastapi` | sí | — | no |
| `starlette` | sí | — | no |
| `uvicorn` | sí | — | no |
| `pydantic` | sí | — | no |
| **`pydantic-core`** | no | **sí** (cp310–cp315) | **no** |
| `python-multipart` | sí | — | no |
| **`uvloop`** | no | **NO** | **sí** |
| **`httptools`** | no | **NO** | **sí** |
| `websockets` | sí | sí | no |

`pydantic-core` es la pieza crítica: es el núcleo en Rust de Pydantic v2, y sin wheel `armv7l`
habría que compilar Rust en un Cortex-A7, lo que en la práctica descarta FastAPI. **Sí publica
esas wheels**, así que la pila es viable.

`uvloop` y `httptools` son exactamente lo que arrastra `uvicorn[standard]`, y ninguno tiene
wheel `armv7l`. Verificado además en un entorno limpio que `pip install uvicorn` **no** los
instala: las transitivas son solo `click` y `h11`.

Comprobado que **todas** las transitivas de la pila son Python puro: `anyio`, `h11`,
`httpcore`, `click`, `certifi`, `idna`, `annotated-types`, `typing-inspection`,
`annotated-doc`. Ninguna necesita compilador.

**Alternativas descartadas**:

- **`uvicorn[standard]`**: es la instalación que recomienda toda la documentación de FastAPI, y
  es precisamente la que rompe el despliegue. Merece un comentario explícito en `pyproject.toml`
  para que nadie lo "arregle" más adelante.
- **Servidor propio sobre `http.server`**: evitaría dependencias, pero reimplementar
  enrutado, validación y documentación es mucho más código propio y más superficie de error
  que una dependencia madura de Python puro.

---

## D2 — Coste de arranque y memoria del proceso de la API

**Decisión**: presupuesto declarado para el proceso de la API: **< 10 s** de arranque en la Pi
2B y **< 120 MB** de memoria residente. Sumado al controlador, el conjunto debe quedar
holgadamente por debajo de la mitad del gigabyte disponible.

**Rationale**: medido en la máquina de desarrollo:

| Medida | Valor |
| --- | ---: |
| `import fastapi, uvicorn, sqlalchemy` en frío | 2,06 s |
| lo mismo en caliente, 3 ejecuciones | 0,326 / 0,325 / 0,345 s |
| RSS del intérprete base | 9,0 MB |
| RSS con `fastapi` | 39,2 MB |
| RSS con `fastapi` + `uvicorn` | 42,1 MB |
| **RSS con `fastapi` + `uvicorn` + `sqlalchemy`** | **52,7 MB** |
| construir la aplicación y servir la primera respuesta | 0,256 s |

Extrapolado ×20, el arranque en la Pi queda en torno a 6-7 s en caliente, y el primer arranque
tras un reinicio puede acercarse a 40 s. Es aceptable para un servicio que corre meses, pero
debe quedar declarado: la unidad de systemd necesita un `TimeoutStartSec` acorde, y un
`ExecStartPre` que valide antes de arrancar añadiría otro arranque completo del intérprete.

Memoria: ~53 MB la API más los ~45 MB medidos para el controlador en la fase anterior son
~100 MB de 1 GB, en torno al 10 %. Sobra margen.

**Medición real tras implementar**, con la aplicación construida de verdad:

| Medida | Valor |
| --- | ---: |
| construir la aplicación completa (importación incluida) | 0,484 s |
| desde importar hasta servir la primera respuesta autenticada | 0,225 s |
| RSS con la aplicación construida | 64,9 MB |

Extrapolado ×20, el arranque en la Pi ronda los 10 s, en el límite del presupuesto declarado y
por encima de la estimación previa de 6-7 s, que solo contaba la importación y no la
construcción de la aplicación. De ahí que la unidad declare `TimeoutStartSec=120s` y que **no**
lleve `ExecStartPre`: pagaría el arranque del intérprete dos veces.

La memoria, 65 MB frente al presupuesto de 120 MB, queda holgada; junto a los ~45 MB del
controlador, unos 110 MB de 1 GB. Falta confirmarlo en el hardware real (tarea T117, manual).

**Alternativa descartada**: compartir un solo proceso para ahorrar ~50 MB. Descartada por el
usuario y por el Principio I: el fail-safe no puede depender de la salud de un servidor web.

---

## D3 — La señal de vida del controlador: tabla nueva, no fichero

**Decisión**: una tabla nueva `controller_heartbeat`, de una sola fila por instalación,
actualizada por el controlador en cada iteración de su bucle. Requiere una migración de
esquema (`0002`).

**Rationale**: el problema que resuelve es el de la historia 2 de la spec: con dos procesos que
solo se comunican por la base de datos, la API leería la última transición registrada y la
presentaría como estado actual aunque el controlador esté muerto.

Alternativas consideradas:

| Opción | Por qué no |
| --- | --- |
| Fichero de latido en disco | No funciona si algún día la API y el controlador viven en máquinas distintas, que es justamente lo que permite PostgreSQL remoto. Y añade un segundo canal de comunicación al que ya existe. |
| Consultar systemd (`systemctl is-active`) | Acopla la API al gestor de servicios, no funciona en desarrollo, y dice si el proceso vive, no si su bucle avanza. Un controlador colgado sigue "activo". |
| Deducirlo de la antigüedad del último plan | El plan se refresca cada `refresh_minutes` (180 por defecto): un controlador muerto pasaría hasta tres horas pareciendo vivo. Inútil. |
| Deducirlo de la última transición | Una noche sin cambios de estado no genera transiciones. Indistinguible de un controlador muerto. |

La tabla es una fila que se actualiza, no un histórico que crece, así que no entra en la
política de retención y su coste es despreciable. Se escribe una vez por `poll_seconds`
(5 s por defecto), es decir del orden de 17 000 escrituras al día sobre **la misma fila**: en
SQLite con WAL eso es una escritura de página, no crecimiento.

Contenido: instante, estado de degradación, identificador del plan en ejecución, y el
`poll_seconds` vigente para que la API pueda derivar la tolerancia sin configuración duplicada.

**Un fallo al escribir el latido no puede parar el control**: se trata igual que el histórico,
con la regla del `HistoryRecorder` de no propagar nunca excepciones.

---

## D4 — Vigencia: tolerancia derivada, y protegida frente a saltos de reloj

**Decisión**: el estado se considera vigente si
`now - heartbeat.updated_at <= max(3 × poll_seconds, 30 s)`. La tolerancia se puede
sobrescribir por entorno. Un latido con instante **futuro** más allá de un margen pequeño se
trata como sospechoso y el estado se marca como no vigente.

**Rationale**: la tolerancia tiene que derivarse del sondeo del controlador para no marcar como
ausente a un controlador simplemente ocupado, y el mínimo de 30 s evita que un `poll_seconds`
muy bajo produzca falsos ausentes por una pausa del recolector de basura o una escritura lenta.

El tratamiento del reloj es la parte que importa (FR-019). La comparación es
`now - updated_at`, así que:

- Si el reloj **retrocede**, la diferencia se vuelve negativa y una comparación ingenua daría
  «vigente» para siempre. Ese es el fallo peligroso: la API afirmaría que el estado es actual
  sin ninguna prueba. De ahí que un instante futuro más allá del margen se trate como no
  vigente, no como vigente.
- Si el reloj **avanza** de golpe, el estado se marca como no vigente hasta el siguiente
  latido. Es el fallo seguro y se corrige solo.

La Raspberry Pi no tiene reloj con batería y la unidad ya espera a `time-sync.target`, así que
un salto en el arranque es un escenario real, no teórico.

---

## D5 — Comparación de la credencial: `secrets.compare_digest`

**Decisión**: comparar el token con `secrets.compare_digest` de la biblioteca estándar.

**Rationale**: una comparación con `==` sale antes en el primer byte distinto, y eso permite
deducir el secreto midiendo tiempos de respuesta byte a byte. `compare_digest` está en la
biblioteca estándar, no añade dependencia, y es la respuesta correcta y barata a FR-010.
Comparar los tokens ya codificados evita además que una diferencia de longitud se filtre.

Rechazo de credenciales triviales al arrancar (FR-011): se rechaza un token vacío, más corto
que un mínimo razonable, o igual a un valor de ejemplo evidente. Sin esto, un despliegue que
copie el fichero de entorno de ejemplo sin editarlo quedaría escuchando sin protección real.

---

## D6 — Endpoints síncronos, no asíncronos

**Decisión**: definir los manejadores como funciones síncronas (`def`, no `async def`).
Starlette las ejecuta en un hilo de un pool.

**Rationale**: el acceso a datos usa SQLAlchemy **síncrono**, decidido en la fase anterior
precisamente para no arrastrar `greenlet`, que es la única dependencia sin wheel `armv7l` que
exigiría compilador. Un manejador `async def` que llamase al repositorio síncrono bloquearía
el bucle de eventos y dejaría la API sin responder mientras espera a una base de datos remota;
la alternativa sería la API asíncrona de SQLAlchemy, que reintroduce `greenlet`.

Un pool de hilos con un puñado de clientes y consultas de milisegundos es más que suficiente:
el perfil de carga previsto es un cliente consultando cada pocos segundos.

**Consecuencia para FR-041**: el tiempo de espera se acota en el motor de base de datos (el
`connect_timeout` del driver y el `pool_timeout` de SQLAlchemy), no con un `asyncio.timeout`
que no aplicaría a un hilo bloqueado.

---

## D7 — Modelos de respuesta explícitos, sin exponer el dominio

**Decisión**: modelos de Pydantic propios para peticiones y respuestas, con conversión explícita
desde las `dataclass` de dominio. No se serializan las dataclasses directamente ni se generan
modelos automáticamente a partir de ellas.

**Rationale**: es lo que hace verificable FR-022, la regla de que la API no puede devolver la
cadena de conexión ni el valor de la clave de AEMET. Con un modelo explícito, un campo nuevo en
el dominio **no** aparece solo en la API: hay que añadirlo a mano, y ese es exactamente el
comportamiento que se quiere para una superficie de red. Serializar el dominio directamente
convierte cada campo futuro en una fuga potencial.

El coste es un mapeo a mano y el riesgo de que se desincronice. Se mitiga con un test que
compare los campos del modelo de respuesta de configuración con los del dominio y falle si
aparece uno nuevo sin decidir explícitamente si se expone.

**Alternativa descartada**: `dataclasses` directamente como `response_model`. Más corto, pero
convierte el modelo de dominio en contrato público y hace de cada campo nuevo una fuga por
defecto.

---

## D8 — Modo de solo lectura cuando el esquema no se comprende

**Decisión**: la API aplica la misma puerta de versión de esquema que el resto del sistema. Con
un esquema **desconocido** no sirve ninguna operación, ni de lectura ni de escritura, y
responde con un error que dice qué hacer. Con un esquema **anterior** pendiente de migrar,
tampoco: la migración es una operación de mantenimiento, no algo que la API deba disparar.

**Rationale**: FR-039. La API no puede escribir configuración sobre columnas que no comprende, y
tampoco puede leerlas con confianza: un campo reinterpretado produciría un panel que muestra
una potencia máxima equivocada. El Principio I resuelve la ambigüedad hacia no operar.

La API **nunca** migra el esquema. Migrar desde una petición HTTP significaría que un cliente
puede alterar la estructura de la base de datos; queda en la CLI, que es donde ya está.

---

## D9 — Pruebas sin abrir un puerto

**Decisión**: probar la aplicación en proceso con el cliente de pruebas de Starlette sobre el
transporte ASGI, sin arrancar un servidor ni enlazar un puerto. La dependencia de cliente HTTP
va en el extra de desarrollo.

**Rationale**: verificado en un ensayo real que construir la aplicación y obtener la primera
respuesta lleva 0,256 s y **no abre ningún puerto**, lo que satisface FR-048 sin excepciones.

**Hallazgo del ensayo**: Starlette 1.6.0 emite `StarletteDeprecationWarning` al usar su cliente
de pruebas con `httpx`, y pide `httpx2`. Comprobado que `httpx2` 2.12.0 existe, es Python puro,
requiere Python ≥ 3.10 y elimina el aviso. Se declara `httpx2` en el extra de desarrollo, no
`httpx`.

Niveles de prueba:

1. **Unitarios de la lógica de vigencia**: función pura sobre instantes, con reloj inyectado.
   No importan FastAPI.
2. **Integración en proceso**: aplicación completa sobre una base de datos SQLite en fichero
   temporal, con el cliente ASGI. Cubren autenticación, estado, edición, histórico y errores.
3. **Guardias arquitectónicas**: que ningún módulo de la API construya un driver de salida, y
   que el núcleo siga importándose sin el extra `api` instalado.

---

## D10 — Consumo desde otro origen: restrictivo por defecto

**Decisión**: los orígenes admitidos se configuran por entorno y por defecto la lista está
**vacía**, es decir ningún origen externo. El frontend de la fase 3 se despliega junto a la API
o declara su origen explícitamente.

**Rationale**: una configuración permisiva por defecto, combinada con un token que el navegador
guarda, es lo que convierte una API doméstica en algo que cualquier página web visitada podría
intentar usar. Con la lista vacía, el consumo desde otro origen solo funciona cuando alguien lo
declara a propósito.

No se admite comodín cuando hay credenciales: es una combinación que los navegadores rechazan y
que además no tiene sentido para esta superficie.

---

## D11 — La configuración de la API va por entorno, no por base de datos

**Decisión**: dirección de escucha, puerto, token, tolerancia de vigencia y orígenes admitidos
se leen del entorno. No se guardan en la base de datos.

**Rationale**: son los datos que hacen falta **antes** de poder leer la base de datos, y en el
caso del token, antes de poder atender la primera petición. Meterlos en la base de datos
crearía una dependencia circular y, para el token, lo pondría en el sitio del que el
Principio III lo excluye explícitamente.

Es coherente con `DTC_DATABASE_URL`: la localización y las credenciales del almacén nunca viven
en el almacén.

---

## D12 — Errores: un cuerpo uniforme y sin fugas

**Decisión**: todos los errores responden con la misma forma —código estable, mensaje accionable
y, cuando aplica, campo y acumulador ofensores—, y se traducen desde los errores de dominio de
la fase anterior. Ninguna traza ni ruta del sistema de ficheros llega al cliente.

**Rationale**: FR-038 y FR-040. La correspondencia con los errores de dominio ya existentes
evita reinventar la taxonomía:

| Error de dominio | Situación | Código HTTP |
| --- | --- | ---: |
| falta o es inválido el token | no autorizado | 401 |
| `ConfigStoreEmptyError` | sin configuración | 503 |
| `SchemaVersionError` | esquema ausente, atrasado o desconocido | 503 |
| `ConfigStoreUnavailableError` | base de datos inaccesible | 503 |
| `ConfigValidationError` | la configuración resultante sería inválida | 422 |
| `SecretRejectedError` | valor con aspecto de credencial | 422 |
| `ConfigConflictError` | revisión obsoleta | 409 |
| campo o acumulador inexistente | nombre desconocido | 404 |
| identificador de acumulador ya en uso | conflicto de alta | 409 |

El 503 para «base de datos inaccesible» y «esquema desconocido» es deliberado: son situaciones
transitorias o de mantenimiento desde el punto de vista del cliente, no errores de su petición.
Los mensajes ya redactados en la fase anterior son accionables y se reutilizan tal cual, salvo
la comprobación de que ninguno filtra la cadena de conexión.
