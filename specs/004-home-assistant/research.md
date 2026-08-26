# Phase 0 — Research: Integración con Home Assistant

**Feature**: `004-home-assistant` | **Fecha**: 2026-08-27

Mediciones tomadas en la máquina de desarrollo con `paho-mqtt` 2.1.0 y SQLAlchemy 2.0.52 en un
entorno virtual limpio.

---

## D1 — `paho-mqtt`, sincrónico, y sin nada más

**Decisión**: `paho-mqtt>=2.1,<3` en un extra opcional `mqtt`. API sincrónica con su propio hilo
de red (`loop_start`). Prohibida la variante asíncrona.

**Rationale**: consultado el índice de PyPI y comprobado en un entorno limpio:

| Paquete | Python puro | Dependencias que instala | Veredicto |
| --- | :---: | --- | --- |
| **`paho-mqtt` 2.1.0** | **sí** | **ninguna** | elegido |
| `aiomqtt` 2.5.1 | sí | `paho-mqtt`, `typing-extensions` | envoltorio asíncrono; no lo necesitamos |
| `amqtt` 0.12.0 | sí | `dacite`, `psutil`, `pwdlib[argon2]`, **`pyyaml`**, `transitions`, `typer` | descartado |
| `gmqtt` 0.7.0 | sí | `atomicwrites`, `attrs`, **`codecov`**, `coverage`, … | descartado |

`amqtt` **reintroduciría `pyyaml`**, que se retiró deliberadamente del runtime en la fase 1, y
`gmqtt` declara herramientas de cobertura como dependencias de runtime. `paho-mqtt` no instala
absolutamente nada más: verificado que el entorno queda con `paho-mqtt` y nada añadido.

Sincrónico por coherencia: el proyecto es síncrono de extremo a extremo desde la fase 1, y por una
razón concreta —la API asíncrona de SQLAlchemy reintroduce `greenlet`, que es la única dependencia
sin wheel `armv7l`—. `paho` en modo síncrono con su hilo de red interno encaja sin excepciones.

**Alternativa descartada**: hablar MQTT a mano sobre sockets. El protocolo tiene reconexión,
sesiones persistentes, QoS y última voluntad; reimplementarlo sería mucho más código propio que una
dependencia sin dependencias.

---

## D2 — Coste del proceso publicador

**Decisión**: presupuesto declarado de **< 70 MB** de memoria residente y arranque **< 5 s** en la
Pi 2B.

**Rationale**: medido en la máquina de desarrollo:

| Medida | Valor |
| --- | ---: |
| `import paho.mqtt.client` en caliente | 0,060 – 0,072 s |
| RSS del intérprete base | 8,7 MB |
| RSS con `paho` | 29,0 MB |
| **RSS con `paho` + `sqlalchemy`** | **46,8 MB** |
| importación completa de ambos, en frío | 1,32 s |

El publicador lee la base de datos, así que su huella real es la de la última fila. Sumado a lo ya
medido —controlador ~45 MB, API ~65 MB— el conjunto de los cuatro servicios ronda **155 MB de
1 GB**, en torno al 15 %. Queda margen, y esa es la comprobación que faltaba antes de añadir un
cuarto proceso a un dispositivo con 1 GB.

`paho` es la parte barata de esta fase; SQLAlchemy es la caro, y ya estaba pagada.

---

## D3 — La disponibilidad tiene **dos** niveles, y esto es el corazón de la fase

**Decisión**: cada entidad declara **dos** asuntos de disponibilidad, combinados con modo «todos»:

1. Uno global, respaldado por la **última voluntad** del publicador ante el broker.
2. Uno propio del estado de salidas, que refleja si el controlador está visible.

**Rationale**: es la misma distinción de las tres fases anteriores, y aquí hay **dos** formas
distintas de perderla:

| Qué falla | Sin tratarlo, Home Assistant vería | Con los dos niveles |
| --- | --- | --- |
| El publicador muere, o cae el túnel | el último valor publicado, **para siempre** | todo no disponible, por la última voluntad |
| El controlador muere, el publicador vive | el publicador podría publicar «apagado» | las entidades de salida no disponibles; las de configuración siguen disponibles |

Un solo nivel no basta. Con solo la última voluntad, un controlador muerto y un publicador vivo
produciría entidades disponibles con valores que nadie puede confirmar. Con solo el nivel del
estado, un publicador muerto dejaría todo congelado en su último valor.

Y la separación importa: cuando el controlador no está visible, la **configuración** sigue siendo
perfectamente conocida —está en la base de datos— y sus entidades deben seguir disponibles. Solo lo
que depende de ver al controlador se marca no disponible.

La última voluntad se declara **antes** de conectar, con retención, para que el broker la conserve
y la publique en cuanto el publicador desaparezca sin despedirse. Verificado que `paho` expone
`will_set(topic, payload, qos, retain)`.

---

## D4 — Reconexión: la que trae la librería, no una propia

**Decisión**: `reconnect_delay_set(min_delay=1, max_delay=120)` más `connect_async` y
`loop_start`. Un rechazo de credenciales **no** entra en ese bucle.

**Rationale**: verificada la firma real: `reconnect_delay_set(self, min_delay: int = 1,
max_delay: int = 120)`. La librería implementa el reintento con duplicación de espera y tope, que
es exactamente lo que FR-031 y FR-032 piden, y `connect_async` no bloquea al arrancar. Escribir un
bucle propio sería reimplementar peor lo que ya funciona.

La excepción importante es FR-033: un broker que **rechaza las credenciales** no es un broker
inalcanzable. Reintentar cada segundo con una contraseña incorrecta llena registros y algunos
brokers bloquean el cliente. Ese caso se detecta por el código de retorno de la conexión, se
registra de forma accionable, y se espera mucho más —del orden de minutos— o se detiene según lo
que el plan decida.

---

## D5 — La temperatura interior llega por el mismo canal, sin credenciales de Home Assistant

**Decisión**: el publicador **se suscribe** a un asunto por acumulador, configurado en la base de
datos. Quien despliega hace que Home Assistant publique ahí el valor de su sensor.

**Rationale**: la alternativa era consultar la API REST de Home Assistant, y eso exigiría un token
de larga duración de Home Assistant guardado en el dispositivo. Sería un **segundo** secreto, un
**segundo** canal de comunicación y un segundo modo de fallo, cuando ya tenemos uno que funciona.

Suscribirse mantiene un solo transporte y ninguna credencial nueva de Home Assistant. Del lado de
Home Assistant es poco trabajo: la integración de reenvío de estados publica todas las entidades a
MQTT, o basta una automatización de dos líneas por sensor.

**Consecuencia importante**: el mensaje puede traer una fecha, y **no se usa**. La antigüedad se
mide con el instante en que el dispositivo recibió el mensaje (FR-026). Es la tercera vez que esta
lección aparece en el proyecto —el latido en la fase 2, las antigüedades en la fase 3— y aquí una
fecha desfasada haría pasar por reciente una medida vieja, que es precisamente el fallo que la
reserva existe para evitar.

---

## D6 — El modelo térmico gana un parámetro, no una lectura

**Decisión**: `ThermalDemandEngine.calculate` acepta un mapa opcional de temperaturas interiores
por acumulador. Sigue siendo una función determinista sin I/O.

**Rationale**: el Principio II exige que el modelo térmico no lea nada. Pasarle las medidas como
dato lo mantiene puro y probable como función, con la tabla completa de casos —medida válida,
ausente, vieja, absurda— sin ningún doble de red.

El cálculo cambia así:

```text
sin medida (o inservible)   ->  fracción = (objetivo - exterior_prevista) / rango   [ANTERIOR]
con medida válida           ->  fracción = (objetivo - interior_medida) / rango
```

Y en ambos casos se aplican después el factor térmico y los límites mínimo y máximo ya existentes.

Dos consecuencias que hay que escribir en el código, no solo en la spec:

- **Una estancia que ya alcanzó su objetivo pide el mínimo configurado, no cero** (FR-029). El
  mínimo existe por acumulador y tiene una razón física: conservar algo de reserva térmica. Que la
  fórmula dé un número negativo y los límites lo recorten al mínimo es exactamente el
  comportamiento correcto, y conviene que quede dicho para que nadie «arregle» el negativo.
- **Un acumulador sin medida se comporta *idénticamente* a antes de esta fase** (FR-023). Es lo que
  hace que la fase no cambie nada para quien no la use, y merece un test que compare la demanda
  antes y después con la misma entrada.

---

## D7 — Órdenes: dos campos, y a través del repositorio

**Decisión**: dos asuntos de mando por acumulador —habilitación y carga objetivo—. Se aplican con
`ConfigRepository.set_field`, con reintento **una vez** ante conflicto de revisión.

**Rationale**: reutilizar el repositorio significa que la validación, la atomicidad y el bloqueo
optimista son los mismos que ya usan la CLI, la API y el panel. FR-017 exige exactamente eso, y no
relajar nada.

El reintento ante conflicto es necesario y acotado: una orden de Home Assistant llega sin haber
leído la revisión, así que el publicador lee, escribe, y si alguien escribió en medio vuelve a leer
y reintenta **una** vez. Reintentar indefinidamente convertiría una orden en un bucle contra el
panel web.

**Lo que garantiza que ninguna orden accione un relé** (FR-016, SC-006) es estructural: el paquete
del publicador no importa `drivers`, `gpio_driver` ni `controller`. Verificable con la misma
guardia estática que ya protege a `api/`.

FR-015 —que Home Assistant no pueda tocar potencia máxima, pin ni nivel activo— se implementa con
una **lista blanca de dos campos**, no con una lista negra. Una lista negra dejaría fuera cualquier
campo futuro por omisión; una lista blanca lo deja fuera por defecto, que es la dirección correcta
para un canal que atraviesa un túnel.

---

## D8 — Retención para que Home Assistant sobreviva a su propio reinicio

**Decisión**: los mensajes de descubrimiento y de estado se publican **con retención**. Los de
mando, sin ella.

**Rationale**: FR-006. Con retención, un Home Assistant que se reinicia recibe el último valor de
cada asunto en cuanto se suscribe, sin que el publicador tenga que enterarse ni republicar.

Los mensajes de mando **no** se retienen, y esto es importante: una orden retenida se reentregaría
al publicador cada vez que se reconectase, reaplicando una orden vieja. Sería el equivalente a que
el túnel, al volver, deshabilitase un acumulador porque alguien lo pidió hace tres días.

Al retirar un acumulador se publica un mensaje **vacío y retenido** en su asunto de descubrimiento:
así Home Assistant borra la entidad en lugar de quedarse con una huérfana (FR-005).

---

## D9 — Dónde vive cada pieza de configuración

**Decisión**:

| Qué | Dónde | Por qué |
| --- | --- | --- |
| Dirección, puerto, credenciales y cifrado del broker | **entorno** | son secretos y datos necesarios antes de leer la base de datos, igual que `DTC_DATABASE_URL` y `DTC_API_TOKEN` |
| Prefijo de asuntos, cadencia de publicación | **entorno** | pertenecen al despliegue, no a la instalación |
| Asunto de temperatura interior de cada acumulador | **base de datos** | es configuración por acumulador, y debe poder editarse por CLI, API y panel como cualquier otra |
| Tolerancia de antigüedad y rango plausible | **base de datos** | son parámetros de la instalación, no del transporte |

**Rationale**: la línea es la misma de todo el proyecto: lo que se necesita para llegar al almacén
va en el entorno; lo que describe la instalación va en el almacén. Y el asunto de temperatura por
acumulador va en la base de datos precisamente para que el panel web pueda editarlo sin que esta
fase tenga que añadir interfaz.

**Consecuencia**: una migración de esquema, la `0003`. Añade columnas a `heater` y a
`installation`, sin tocar datos existentes, y con valores nulos por defecto para que FR-023 se
cumpla sin más: quien no configure nada no cambia de comportamiento.

---

## D10 — Pruebas sin broker, sin red y sin Home Assistant

**Decisión**: el cliente de mensajería vive detrás de un `Protocol` inyectable, con un doble en
memoria que registra publicaciones y suscripciones y permite inyectar mensajes entrantes,
desconexiones y rechazos de credenciales.

**Rationale**: FR-042. Ningún test toca un broker, igual que ninguno toca la red ni el hardware. El
doble es además la única forma razonable de probar los casos que importan: qué se publica al perder
la conexión, en qué orden se republica al reconectar, y qué pasa con una orden retenida.

Lo que hay que cubrir con más cuidado, por consecuencia si falla:

1. **Disponibilidad en los dos niveles** (D3): la tabla completa de las cuatro situaciones del
   controlador cruzada con publicador vivo y muerto.
2. **La última voluntad se declara antes de conectar**, y con retención. Declararla después no
   sirve para nada y no fallaría ningún test ingenuo.
3. **El orden al reconectar**: descubrimiento y luego estado.
4. **La lista blanca de órdenes**: que los tres campos eléctricos se rechacen, y que un campo nuevo
   quede fuera por defecto.
5. **Los cuatro caminos de reserva térmica**: sin medida, medida vieja, medida absurda, y
   recuperación.
6. **Que un acumulador sin medida calcule exactamente lo mismo que antes de esta fase.**

---

## D11 — Un cuarto servicio, y la guardia que lo mantiene inofensivo

**Decisión**: unidad de systemd propia, sin ninguna dependencia declarada respecto al controlador
ni a la API. Guardia estática de que el paquete no importa nada capaz de conmutar una salida.

**Rationale**: es la misma decisión que en la fase 2 y por la misma razón, con un argumento extra:
esta fase añade **E/S de red hacia el exterior a través de un túnel**, que es la clase de
dependencia que más conviene mantener lejos del proceso cuyo fail-safe no es negociable.

Detener el publicador durante horas no debe producir ningún cambio observable en el control
(SC-010), y eso es una propiedad de la topología, no de la buena intención.

---

## D12 — Cifrado al broker: opcional, y explicado

**Decisión**: `tls_set` disponible tras una opción de configuración, desactivado por defecto. La
documentación explica cuándo hace falta.

**Rationale**: FR-034. Si el broker se alcanza **por el túnel**, el túnel ya cifra y añadir TLS es
redundante; si se alcanza por una red no confiable, es imprescindible. La decisión depende del
despliegue, así que el proyecto ofrece la opción y explica el criterio en lugar de imponer uno.

Verificado que `paho` expone `tls_set`, así que la opción no cuesta código propio.
