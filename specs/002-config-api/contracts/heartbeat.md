# Contract — Señal de vida del controlador

**Feature**: `002-config-api`

La única cosa nueva que el controlador tiene que hacer, y la única forma que tiene la API de
saber si lo que lee es actual.

## Frontera

```text
HeartbeatPublisher (Protocol)

    publish(now, degraded, plan_ref, poll_seconds, driver_kind) -> None
        Registra que el controlador está vivo en este instante.
        NUNCA propaga una excepción: un fallo se registra como error y el
        control continúa. Misma regla que HistoryRecorder.

    read() -> Heartbeat | None
        Devuelve el último latido, o None si nunca hubo ninguno.
        Lo usa la API, no el controlador.
```

## Quién escribe y cuándo

El controlador publica **en cada iteración de su bucle**, es decir cada `poll_seconds`, no solo
cuando refresca el plan. Publicar solo en el refresco dejaría hasta `refresh_minutes` (180 por
defecto) de silencio, y un controlador muerto pasaría tres horas pareciendo vivo.

## Cómo se interpreta la antigüedad

```text
tolerancia = DTC_API_STALE_SECONDS  o  max(3 × poll_seconds, 30 s)
margen_reloj = 5 s

sin latido                          -> never_seen
updated_at > now + margen_reloj     -> stale       (latido del futuro)
now - updated_at > tolerancia       -> stale
degraded                            -> live_degraded
resto                               -> live
```

El caso del latido futuro es el importante. Si el reloj del sistema retrocede —y la Raspberry Pi
no tiene reloj con batería, por lo que es un escenario real en cada arranque antes de
sincronizar—, `now - updated_at` se vuelve negativo y una comparación ingenua daría «vigente»
indefinidamente. La API afirmaría que su información es actual sin ninguna prueba. Se resuelve
hacia `stale`, que es el estado honesto.

El factor 3 sobre `poll_seconds` da margen a un controlador simplemente ocupado; el mínimo de
30 s evita falsos ausentes cuando `poll_seconds` es muy bajo.

## Garantía no negociable

Publicar el latido **no puede** hacer fallar el bucle de control. Un fallo de escritura se
registra como error y el controlador sigue aplicando su plan. La consecuencia visible es que la
API marcará el estado como no vigente: exactamente lo correcto, porque en ese momento la API no
tiene prueba de nada.

Es la misma asimetría del `HistoryRecorder` de la fase anterior: sin configuración no se puede
decidir qué relé cerrar; sin observabilidad, sí.
