# Conservar el slot activo durante la replanificación por desviación

Status: approved

## Goal

Cerrar el hueco de control que aparece cuando una replanificación automática por
desviación sustituye el plan justo después de un límite de slot. El código actual
incluye el slot recién iniciado en la reproyección de `plan_deviation.py`, pero
`charge_planning.py` alinea el nuevo horizonte hacia el siguiente límite y el
controlador solo ejecuta el intervalo que contiene el instante observado; la
sustitución puede dejar sin slot efectivo los instantes intermedios. El resultado
debe conservar el slot en curso, sus consignas y sus salidas hasta su fin, y
recalcular solo desde el límite siguiente. Fuera de alcance: la exclusión
`missing_required_state` de Buhardilla, la política general de optimización, la
duración de los slots, la configuración GPIO y las migraciones salvo necesidad
inevitable.

## Requirements

- R1: Una replanificación automática por desviación debe identificar el slot del plan gobernante que contiene `now` con límites inclusivo al inicio y exclusivo al fin; ese slot sigue siendo efectivo aunque `now` esté unos microsegundos después de su inicio.
- R2: Mientras ese slot esté en curso, la sustitución debe conservar exactamente sus límites, decisiones de acumuladores y consignas/objetivos de ejecución ya previstos hasta su finalización; no puede reemplazarlos por un cálculo iniciado después del límite que acaba de pasar.
- R3: El nuevo cálculo debe producir únicamente el futuro desde el fin del slot conservado. La secuencia efectiva debe ser contigua y tener exactamente un slot en cada instante desde `now` hasta el siguiente límite, seguido inmediatamente por el primer slot recalculado, sin intervalos vacíos ni solapes.
- R4: La persistencia del plan automático y del plan consumido por el controlador debe representar esa secuencia efectiva; al recargarla, el controlador debe mantener las salidas del slot conservado y aplicar el siguiente slot recalculado únicamente en su límite.
- R5: Estado API debe proyectar el plan/slot efectivo conservado durante la transición, sin introducir una ausencia de plan ni alterar las reglas existentes de liveness, `output_on` nulo o ventana visible.
- R6: Cuando no existe un slot activo que conservar, la planificación mantiene la semántica actual: el límite exacto se usa tal cual y un instante intermedio comienza en el siguiente límite, sin cambiar la duración configurada de los slots.

## Acceptance

- A1: Una regresión determinista fija un slot de 30 minutos que comienza en `B`, ejecuta la replanificación en `B + 1 microsegundo` y verifica que el slot vigente es `[B, B+30 minutos)`, conserva sus acumuladores/consigna y no aparece ningún hueco hasta `B+30 minutos`.
- A2: La misma regresión ejecuta `ChargeController` con un driver simulado o grabador y verifica que a `B + 1 microsegundo` permanecen las salidas previstas del slot vigente y que en `B+30 minutos` se hace directamente la transición a las salidas del futuro, sin pulso intermedio de apagado.
- A3: Las pruebas verifican que la replanificación no vuelve a decidir el slot conservado y que el primer intervalo nuevo empieza exactamente en su fin; también cubren la inclusión única del slot recién iniciado en la reproyección de desviación.
- A4: Una prueba de persistencia guarda y recarga la secuencia sustituida, y una prueba de `GET /api/v1/status` en el mismo instante confirma el slot efectivo y la continuidad visible hasta el límite siguiente.
- A5: Las pruebas existentes de planificación/controlador para un instante sin slot activo siguen demostrando el redondeo al siguiente límite; la regresión no requiere GPIO físico ni cambia la duración de slots.
- A6: La verificación focalizada cubre `test_plan_deviation.py`, planificación de energía/runtime, persistencia del plan activo, `test_service.py`/`test_controller.py` y `test_api_status.py`; después, `make check` pasa sin modificar la semántica fuera de alcance.
