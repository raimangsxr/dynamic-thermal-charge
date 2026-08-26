# Phase 1 — Data Model: Panel web

**Feature**: `003-web-panel` | **Fecha**: 2026-08-26

Esta fase **no persiste nada**. No hay tablas nuevas, no hay migración, y `src/` no cambia. El
modelo aquí es el de la vista: cómo se representa en el navegador lo que devuelve la API, y qué
decisiones de representación son obligatorias.

Los tipos del cliente se derivan del contrato de
[`specs/002-config-api/contracts/http-api.md`](../002-config-api/contracts/http-api.md).

---

## El tipo que sostiene toda la fase: el estado de una salida

```text
OutputState = { kind: "on" }        // encendido, confirmado
            | { kind: "off" }       // apagado, confirmado
            | { kind: "unknown",    // sin confirmar
                lastKnown: boolean,
                changedAt: Date }
```

**Tres valores, no un booleano.** Es la decisión central de esta fase (research D8).

La API devuelve `output_on` como `true`, `false` o `null`, y `null` significa «no tengo prueba de
nada», no «apagado». Un booleano en el modelo del panel colapsaría `null` en `false` en la primera
conversión, y desde ahí la información estaría perdida sin que nada avisara: la pantalla mostraría
un acumulador apagado con total seguridad cuando en realidad podría estar cargando 2,8 kW.

Con un tipo de tres variantes, el comprobador de tipos **obliga** a decidir qué se pinta en el
tercer caso, en cada sitio donde se pinta. Esa obligación es el mecanismo, no un comentario.

### Reglas de presentación

| Variante | Qué se muestra | Qué NO se muestra |
| --- | --- | --- |
| `on` | indicador de carga activa | — |
| `off` | indicador de reposo | — |
| `unknown` | el último valor conocido, **etiquetado como pasado**, con su instante | nunca con la misma apariencia que `on` u `off` |

Las tres apariencias deben distinguirse **sin depender del color** (FR-036): forma o texto además
del color. Un panel que informa sobre una instalación eléctrica no puede excluir a quien no
distingue verde de gris.

---

## Vista de estado

```text
StatusView
  observedAt         instante de la consulta, según la API
  controller         ControllerView
  power              PowerView | null     <- null cuando no hay vigencia
  heaters            HeaterView[]
  plan               PlanView | null      <- null cuando ninguna ventana contiene el instante
  forecast           ForecastView | null
  allocations        AllocationView[]

ControllerView
  liveness           "live" | "live_degraded" | "stale" | "never_seen"
  stateIsCurrent     boolean
  ageSeconds         number | null        <- de la API, NO calculado en local
  lastSeenAt         Date | null
  startedAt          Date | null
  degraded           boolean
  driverKind         "simulated" | "gpio" | null
  multipleControllers boolean             <- advertencia prominente si es true

HeaterView
  id, name, enabled, powerW
  output             OutputState          <- el tipo de tres variantes
```

**`power` es `null`, no cero.** Cuando el estado no es vigente la API no publica potencia, y el
panel no puede rellenar ese hueco con un cero: un cero afirma que no se está consumiendo nada.

**`ageSeconds` viene de la API** (research D9). No se calcula como `Date.now() - lastSeenAt`: el
reloj del navegador y el de la Raspberry Pi pueden diferir, y la Pi no tiene reloj con batería.
Calcularlo en local produciría antigüedades negativas o de horas justo en el indicador del que
depende que el operador confíe en lo que ve.

---

## Formulario de configuración

```text
ConfigForm
  revision           number               <- la que se leyó; se envía en cada escritura
  values             campo -> valor actual
  pending            campo -> valor editado sin guardar
  errors             campo -> mensaje de la API
  dirty              boolean
```

- **`revision` es obligatoria en cada escritura.** Es el bloqueo optimista de la API. Un conflicto
  no es un error a evitar: es la protección funcionando, y se presenta como «la configuración
  cambió, reléela» con la acción a mano.
- **`errors` se indexa por campo**, porque la API devuelve el campo ofensor cuando lo conoce
  (FR-018). Un mensaje genérico desperdicia información que la API ya se tomó el trabajo de dar.
- **`pending` sobrevive a un fallo de red** (FR-033): si la escritura no se aplica, lo introducido
  sigue en el formulario.
- **`dirty` gobierna el aviso al navegar** (FR-022).

### Campos con consecuencias eléctricas

Estos tres exigen confirmación explícita que diga qué se va a cambiar (FR-020):

| Campo | Por qué |
| --- | --- |
| `max_total_power_kw` | un valor alto de más sobrecarga el cuadro |
| `pin` de un acumulador | un pin equivocado gobierna el relé equivocado |
| `active_high` | invertirlo deja el relé cerrado en reposo |

El resto se cambia sin ceremonia. Pedir confirmación para todo enseña a confirmar sin leer, que es
peor que no pedirla.

---

## Página de histórico

```text
HistoryPage<T>
  items              T[]
  limitApplied       number
  hasMore            boolean
  nextCursor         string | null        <- opaco; no se interpreta ni se construye
  filter             { from?, to?, heaterId? }
```

El cursor es **opaco** para el panel: se reenvía tal cual. Interpretarlo o construirlo sería
reimplementar la paginación de la API y romperse en la primera inserción entre páginas.

Un acumulador presente en el histórico pero ausente de la configuración se marca como tal
(FR-028): existió y se eliminó, y su histórico se conserva a propósito.

---

## Traducción de errores

Cada código estable de la API se traduce a una explicación accionable (FR-031). La tabla es el
contrato de esta fase con el operador:

| Código de la API | Qué se muestra | Acción ofrecida |
| --- | --- | --- |
| `unauthorized` | la credencial no es válida o ha caducado | volver a la pantalla de acceso |
| `not_found` | el campo o el acumulador no existe | — |
| `already_exists` | ese identificador ya está en uso | elegir otro |
| `config_conflict` | la configuración cambió mientras editabas | releer y reintentar |
| `validation_failed` | el mensaje de la API, **junto al campo** | corregir el campo |
| `secret_rejected` | los secretos van por variable de entorno, no aquí | — |
| `bad_request` | el rango o la página no son válidos | corregir el filtro |
| `no_configuration` | la base de datos no tiene instalación | ejecutar `dtc db init` **en el dispositivo** |
| `schema_unusable` | el esquema necesita intervención | ejecutar `dtc db upgrade` **en el dispositivo** |
| `store_unavailable` | la base de datos no responde | comprobar la red si es remota |
| sin respuesta | la API no responde | conservar lo último, marcado como no actual |

Las dos filas del esquema son las que más importan redactar bien: el panel **no puede** arreglarlo,
y decirlo explícitamente evita que el operador busque un botón que no existe (FR-032).

---

## Sesión

```text
Session
  token              string               <- solo en sessionStorage y en memoria
  authenticated      boolean
```

Lo que **nunca** ocurre (FR-003): el token no aparece en la dirección de la página, ni en
parámetros de consulta, ni en `localStorage`. En la dirección quedaría en el historial del
navegador y en los registros de nginx.

---

## Lo que esta fase no añade

- Ninguna tabla, ninguna migración, ningún cambio en `src/dynamic_thermal_charge/`.
- Ninguna capacidad de accionar salidas: la API no la ofrece, y el panel no debe insinuar que
  exista.
- Ninguna agregación ni serie temporal: el histórico se presenta tal como lo devuelve la API.
