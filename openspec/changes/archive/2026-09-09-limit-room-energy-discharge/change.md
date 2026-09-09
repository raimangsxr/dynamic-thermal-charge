# Limitar la descarga térmica por intervalo

Status: approved

## Goal

Evitar que la planificación del modelo acoplado de sala y acumulador proyecte
una descarga instantánea superior a la que puede entregar el elemento
resistivo. La energía almacenada, la temperatura y los déficits deben calcularse
con el mismo límite físico por intervalo.

## Requirements

- R1: Cada intervalo del modelo de energía limita el calor entregado por acumulador a `potencia nominal × duración real del intervalo`, sin superar tampoco la energía disponible tras la carga del intervalo.
- R2: El optimizador MILP aplica ese mismo límite por acumulador e intervalo; una consigna que requiera más calor conserva su déficit y deja el plan como `DEGRADED` en vez de producir una transición de energía imposible.
- R3: El balance de energía almacenada, la temperatura siguiente, las explicaciones y las vistas de auditoría usan el calor efectivamente limitado, manteniendo coherencia entre el helper y el plan optimizado.
- R4: Las restricciones de potencia eléctrica de carga y el planificador legado conservan su comportamiento actual; no se introduce una segunda configuración de potencia en este cambio.

## Acceptance

- A1: Un acumulador de 2,4 kW en un slot de 30 minutos no puede entregar más de 1,2 kWh; una petición de 6,7584 kWh queda limitada y no lleva un SOC del 50,7% al 15,5% en ese slot.
- A2: Una planificación con una consigna que solo sería alcanzable usando más del límite de descarga devuelve el déficit térmico proyectado y estado `DEGRADED`, conservando energía almacenada no negativa.
- A3: Los tests cubren por separado el límite del helper y la restricción del optimizador, y `make check` pasa sin regresiones.
