# Design

## Durable decisions

El plan distingue el calor forzado, inevitable mientras quede energía almacenada,
del calor controlado que requiere una descarga habilitada. Esa distinción se
conserva en la auditoría, las explicaciones y el accionamiento MQTT; el calor
forzado no se trata como calor controlable o desperdiciado.

La calibración incorpora la fuga en todas las fases y reserva la compuerta para
el calor controlado, de forma que las fases sin descarga sigan aportando
evidencia térmica.
