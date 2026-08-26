# Phase 1 — Data Model: API HTTP de estado y configuración

**Feature**: `002-config-api` | **Fecha**: 2026-08-26

Esta fase **no** redefine el modelo de configuración ni el de histórico: son los de
[`specs/001-config-database/data-model.md`](../001-config-database/data-model.md) y se
reutilizan sin cambios. Aquí hay una sola tabla nueva y un conjunto de modelos de
representación que no se persisten.

---

## Tabla nueva: `controller_heartbeat`

Una sola fila por instalación. **Se actualiza, no crece.** Por eso queda fuera de la política de
retención.

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `id` | entero, PK | no | |
| `installation_id` | entero, FK → `installation.id` | no | `ON DELETE CASCADE`, **único** |
| `updated_at` | instante UTC | no | instante del último latido |
| `started_at` | instante UTC | no | arranque del proceso controlador actual |
| `degraded` | booleano | no | el controlador no alcanza la base de datos o su proveedor |
| `plan_id` | entero, FK → `plan.id` | sí | `ON DELETE SET NULL`. Plan que está ejecutando |
| `poll_seconds` | real | no | > 0. Sondeo vigente, para que la API derive la tolerancia |
| `driver_kind` | texto | no | `simulated` o `gpio`. Con qué driver arrancó |

Restricción única sobre `installation_id`: hay como máximo un controlador por instalación.

**Por qué una tabla y no un fichero** (research D3): con PostgreSQL remoto, la API y el
controlador pueden vivir en máquinas distintas, y un fichero de latido no cruza esa frontera.
Además el canal de comunicación entre los dos procesos ya es la base de datos; añadir un segundo
canal duplicaría los modos de fallo.

**Por qué `poll_seconds` viaja en el latido**: la tolerancia de vigencia se deriva del sondeo del
controlador. Si la API lo leyera de la configuración, y el controlador arrancó con una
configuración anterior, la tolerancia no correspondería al proceso real. El latido lleva el valor
con el que el controlador está funcionando de verdad.

**Por qué `started_at` y `driver_kind`**: distinguir «el controlador se reinició hace un minuto»
de «lleva tres meses en marcha» es información de diagnóstico que el operador necesita, y saber
si arrancó en modo simulado o con GPIO real evita la confusión de ver un plan ejecutándose sin
que ningún relé se mueva.

**Escrituras**: una por `poll_seconds`, 5 s por defecto, siempre sobre la misma fila. Del orden
de 17 000 actualizaciones al día que no hacen crecer la base de datos. Un fallo al escribir el
latido se registra como error y **no** interrumpe el control: misma regla que el histórico.

---

## Estado derivado, no almacenado

Nada de lo siguiente se persiste. Se calcula en el momento de la consulta a partir de la
configuración, el histórico y el latido.

### Vigencia

```text
antigüedad  = now - heartbeat.updated_at
tolerancia  = override_de_entorno  o  max(3 × heartbeat.poll_seconds, 30 s)

sin fila de latido            -> NEVER_SEEN
antigüedad > tolerancia       -> STALE
antigüedad < -margen_reloj    -> STALE     (latido del futuro: reloj sospechoso)
en otro caso y degraded       -> LIVE_DEGRADED
en otro caso                  -> LIVE
```

El caso del latido futuro es el que importa (research D4): una comparación ingenua daría
«vigente para siempre» si el reloj del sistema retrocede, y la API afirmaría que el estado es
actual sin ninguna prueba. Se resuelve hacia el estado seguro, que aquí es «no lo sé».

### Estado de las salidas

Se deriva de la **última transición por acumulador** en `output_transition`. Un acumulador sin
ninguna transición registrada se considera apagado, que es el estado en que todo driver
inicializa (Principio I).

Cuando la vigencia es `STALE` o `NEVER_SEEN`, ese estado se presenta como **último estado
conocido con su instante**, nunca como estado actual, y la respuesta no afirma que ningún
acumulador esté activo.

### Potencia instantánea

Suma de `power_w` de los acumuladores que constan como activos, y su porcentaje de
`max_total_power_w`. Se calcula solo cuando la vigencia es `LIVE` o `LIVE_DEGRADED`; con el
estado no vigente no se publica una potencia que nadie puede confirmar.

### Plan en curso

El plan cuya ventana contiene el instante de la consulta. Si no hay ninguno, se indica
explícitamente en lugar de devolver el último plan pasado como si estuviera vigente.

---

## Modelos de representación

Explícitos y separados del dominio (research D7). Un campo nuevo en el dominio **no** aparece
solo en la API: hay que añadirlo a mano, y eso es exactamente lo que se quiere para una
superficie de red.

### Estado

- **StatusResponse**: instante de la consulta, salud del controlador, vigencia, acumuladores con
  su estado e instante del último cambio, potencia instantánea y su porcentaje cuando procede,
  plan en curso, previsión utilizada y reparto por acumulador.
- **ControllerHealth**: vigencia, instante del último latido, antigüedad en segundos, instante de
  arranque, si está degradado, y con qué driver arrancó.
- **HeaterState**: identificador, nombre, si está habilitado, estado de la salida, instante del
  último cambio y potencia nominal.
- **PlanSummary**: ventana, resolución de intervalo, revisión de configuración con la que se
  generó, e intervalos por acumulador.
- **ForecastSummary**: fecha, temperaturas, origen (`aemet`, `simulated` o `fallback`) y
  municipio cuando lo haya.
- **AllocationSummary**: por acumulador, minutos solicitados, asignados y no atendidos.

### Configuración

- **ConfigResponse**: la instalación completa con su revisión de configuración y la revisión de
  esquema. **Nunca** incluye la localización de la base de datos ni el valor de la clave del
  proveedor; del proveedor solo el **nombre** de su variable de entorno.
- **HeaterResponse**: un acumulador con su salida y su perfil térmico.
- **SetFieldRequest**: revisión sobre la que se basa el cambio, campo y valor.
- **AddHeaterRequest**: los datos obligatorios y opcionales de un acumulador nuevo, más la
  revisión.
- **ChangeResponse**: entidad, clave, campo, valor anterior, valor nuevo, acción y revisiones.

### Histórico

- **Page**: los elementos, el rango temporal cubierto, el tamaño de página aplicado y si hay más
  resultados.
- **PlanHistoryItem**, **ForecastHistoryItem**, **TransitionHistoryItem**: proyecciones de solo
  lectura del histórico ya definido.

### Errores

- **ErrorResponse**: código estable legible por máquina, mensaje accionable, y campo y
  acumulador ofensores cuando aplique. Ninguna traza, ninguna ruta del sistema de ficheros,
  ningún fragmento de cadena de conexión.

---

## Correspondencia con la fase anterior

| Necesidad de la API | De dónde sale |
| --- | --- |
| Configuración validada y su revisión | `ConfigRepository.current()` |
| Edición con validación y bloqueo optimista | `ConfigRepository.set_field/add_heater/remove_heater` |
| Planes, previsiones, transiciones | tablas de histórico de la fase 1 |
| Limpieza de retención | `HistoryRecorder.prune()` |
| Estado del esquema | `SchemaGate` |
| Errores accionables | jerarquía de errores de dominio de la fase 1 |
| **Salud del controlador** | **`controller_heartbeat`, nuevo en esta fase** |

Se añade además una operación de consulta de histórico paginada al borde de persistencia, que la
fase 1 no necesitaba: hasta ahora el histórico solo se escribía y se limpiaba.

---

## Migración

Revisión `0002_controller_heartbeat`: crea la tabla. No toca ninguna tabla existente, así que no
necesita reescritura por lotes y es segura en ambos motores.

Consecuencia para la puerta de versión: la constante de revisiones conocidas pasa a tener dos
entradas, y una base de datos de la fase 1 se detecta como `BEHIND` con la sugerencia de migrar,
no como desconocida. Es el camino de actualización que la fase 1 dejó preparado.
