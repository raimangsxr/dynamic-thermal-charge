# Mando MQTT de activación de la descarga

Status: approved

## Goal

El sistema planifica la emisión de calor pero no la acciona: la descarga del
acumulador la activa alguien más, así que el plan es una previsión y no una
orden. Activar y desactivar la descarga por MQTT según el plan activo,
publicando también la consigna vigente para que el termostato del acumulador
module su compuerta durante la ventana.

## Requirements

- R1: Cuando el plan activo indica emisión para un acumulador en el intervalo vigente, el controlador publica `ON` en el `damper_topic` de ese acumulador para activar su descarga; cuando deja de indicarla, publica `OFF` para desactivarla.
- R2: La emisión está indicada mientras una consigna esté activa en el intervalo vigente y también en un intervalo anterior sin consigna en el que el plan proyecte calor entregado para ese acumulador.
- R3: Mientras la descarga esté activada, el controlador publica la temperatura objetivo vigente en el topic de consigna del acumulador. En un intervalo de anticipación la consigna publicada es la de la próxima consigna del plan que motiva esa emisión.
- R4: Cada ciclo de control reafirma el estado de descarga y, cuando corresponde, la consigna de cada acumulador. Los mensajes de mando no se publican con retención.
- R5: El controlador publica `OFF` y no publica consigna cuando no hay plan activo, el plan es `INVALID`, el control automático está desactivado, el acumulador está en modo `OFF`, la prueba de relés está en curso o el controlador se detiene de forma ordenada.
- R6: Un acumulador sin `damper_topic` configurado no recibe mando alguno; la condición se registra una vez y no interrumpe el ciclo ni el mando del resto de acumuladores.
- R7: El estado MQTT publicado por acumulador incluye si la descarga está activada, de forma distinguible de la posición de compuerta recibida por telemetría.
- R8: Una posición de compuerta cerrada mientras la descarga está activada no es una discrepancia: el termostato del acumulador cierra al alcanzar la consigna y vuelve a abrir cuando la estancia se enfría. El sistema no compara ambos valores ni genera alerta por su diferencia.
- R9: El topic de consigna se configura y persiste por acumulador por la misma vía y con la misma validación que `damper_topic`, y ambos son editables en el panel de configuración del acumulador.
- R10: Un fallo de publicación MQTT no interrumpe el ciclo de control ni el accionamiento de las salidas de carga, y se registra de forma colapsada como el resto de fallos de publicación.
- R11: La formulación de la planificación no cambia: el calor entregado sigue siendo una variable modulable porque el termostato del acumulador modula hasta la consigna publicada. Las restricciones eléctricas de carga, el accionamiento GPIO y la prueba de relés conservan su comportamiento.

## Acceptance

- A1: Con un plan activo cuya consigna está activa en el intervalo vigente, el ciclo publica `ON` en el `damper_topic` del acumulador y su consigna en el topic de consigna, ambos sin retención.
- A2: Al terminar el intervalo de consigna, el siguiente ciclo publica `OFF` y deja de publicar consigna.
- A3: En un intervalo sin consigna en el que el plan proyecta calor entregado, se publica `ON` y la consigna de la próxima ventana del plan.
- A4: Sin plan activo, con plan `INVALID`, con control automático desactivado, con el acumulador en modo `OFF`, durante una prueba de relés y en la parada ordenada, se publica `OFF`.
- A5: Un acumulador sin `damper_topic` no genera publicaciones y el resto de acumuladores del mismo ciclo reciben su mando.
- A6: Con la descarga activada y una telemetría de posición de compuerta al 0%, el ciclo mantiene `ON` y no registra ni publica una discrepancia.
- A7: Un error del cliente MQTT durante la publicación deja el ciclo de control completo, las salidas de carga aplicadas y un único registro por transición de fallo.
- A8: La API y el panel guardan y devuelven ambos topics, normalizan un valor en blanco a ausente y conservan la detección de configuración cambiada; `npm test`, `npm run build` y `make check` pasan.

## Decisions

- D1: El mando se deriva del plan activo persistido (`store.planning.active_plan()`), que ya conserva `target_temperature_c` y `heat_delivered_kwh` por acumulador e intervalo. Así el mando coincide con el plan que ve el operador y sobrevive a un reinicio sin esperar una replanificación.
- D2: El mando es una habilitación de la descarga, no una orden de apertura: durante toda la ventana de consigna se mantiene activada aunque el plan proyecte cero calor en algún intervalo templado, y es el termostato del acumulador el que cierra y abre su compuerta cíclicamente para no sobrecalentar la estancia. Fuera de la ventana, el calor proyectado es lo que activa la descarga, con un umbral de 1e-6 kWh.
- D3: El topic de consigna es una columna nueva `setpoint_topic` en `heater_charge_config`, junto a `damper_topic`. No se reutiliza el campo heredado `target_temperature_topic` de `Heater`, que era un topic de lectura y está marcado como obsoleto.
- D4: El payload de la consigna es el número decimal en grados Celsius con un decimal, coherente con la convención de payloads simples de los mandos existentes; el de la descarga es `ON` u `OFF`, como `set/enabled`.
- D5: El estado comandado no se persiste: se recalcula en cada ciclo desde el plan activo y se reafirma, así que no hay una segunda fuente de verdad que pueda quedar obsoleta.
- D6: No se añade una entidad de mando de compuerta a Home Assistant; se conserva la decisión documentada de no ofrecer un mando manual de compuerta ni un modo HEAT.
- D7: El simulador de acumuladores conserva su modelo actual y no reacciona al mando de descarga en este cambio.
- D8: `damper_topic` existe hoy en la API pero no tiene campo en el panel. Este cambio añade los dos campos a la vez, porque exponer solo la consigna dejaría la configuración de mandos a medias.
- D9: Este cambio hace físicamente efectiva la puerta de emisión del cambio `soc-dependent-emission-limit`: la descarga desactivada fuera de las ventanas de emisión es lo que garantiza que no haya emisión sin demanda. Los dos cambios son independientes en el código y pueden implementarse por separado.

## Tasks

- [ ] T1: Añadir `setpoint_topic` a `heater_charge_config` con migración Alembic, `schema.py`, `active_schema.py` y su lectura y escritura en `persistence/home_assistant.py`.
- [ ] T2: Exponer y validar `setpoint_topic` en los esquemas y en la ruta de configuración de planificación del acumulador, junto a `damper_topic`.
- [ ] T3: Añadir los campos de `damper_topic` y `setpoint_topic` al formulario de acumuladores del panel, con sus tipos, su texto de ayuda y sus pruebas.
- [ ] T4: Añadir un módulo de mando de descarga en `mqtt/` que, dado el plan activo, el instante y el estado de control, resuelva de forma pura el estado de descarga y la consigna por acumulador.
- [ ] T5: Publicar ese resultado sin retención desde `ControllerService`, reafirmándolo cada ciclo y aplicando la desactivación de R5 en la parada ordenada y en la prueba de relés.
- [ ] T6: Incluir el estado de descarga comandado en la proyección de estado MQTT por acumulador.
- [ ] T7: Cubrir con tests la resolución pura, la reafirmación por ciclo, cada condición de desactivación de R5, la ausencia de `damper_topic`, la telemetría de compuerta cerrada con descarga activada y la tolerancia a un fallo de publicación.
- [ ] T8: Actualizar `openspec/specs/planning/spec.md` con el requisito de accionamiento de la descarga y la tabla de topics y la sección de Home Assistant de `README.md`.
- [ ] T9: Ejecutar `make check`.
