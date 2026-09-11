# Capacidad de emisión dependiente del estado de carga

Status: approved

## Goal

La planificación proyecta hoy que un acumulador entrega calor a plena potencia
de carga con cualquier estado de carga, así que un acumulador al 20% aparece
capaz de subir la temperatura igual que uno al 100% hasta agotar su energía de
golpe. Modelar la emisión real, que decae con el estado de carga, para que el
plan reconozca cuándo un acumulador poco cargado ya no puede alcanzar ni
mantener la consigna.

## Requirements

- R1: Cada acumulador tiene horas de descarga nominal del fabricante y un porcentaje de emisión residual; la potencia máxima de emisión es `capacidad kWh / horas de descarga nominal` y la residual es ese porcentaje de la máxima.
- R2: El calor entregable en un intervalo se limita a `(P_residual + (P_emisión − P_residual) × SOC) × duración real del intervalo`, con el SOC del borde inicial del intervalo, además de los límites vigentes de energía disponible tras la carga.
- R3: El helper del modelo de sala y el optimizador MILP aplican el mismo límite, de forma que la energía almacenada, la temperatura proyectada y los déficits coinciden entre la simulación auditable y el plan resuelto.
- R4: Un acumulador cuyo estado de carga no permite alcanzar o mantener la consigna conserva el déficit de temperatura de los bordes afectados y deja el plan como `DEGRADED`, sin proyectar una emisión imposible.
- R5: El calor entregado es cero en los intervalos sin consigna activa a partir de los cuales ninguna consigna del horizonte queda por delante; en los intervalos previos a una consigna sigue permitida la emisión, de modo que se conserva el precalentamiento antes de su borde inicial.
- R6: Cada intervalo del plan y de la vista previa conserva el límite de emisión aplicado en kWh, para distinguir un déficit por falta de energía almacenada de uno por falta de capacidad de emisión.
- R7: Las horas de descarga nominal y el porcentaje de emisión residual se editan y persisten por acumulador con validación: horas estrictamente positivas y porcentaje entre 0 y 100 inclusive.
- R8: Las restricciones eléctricas de carga, el planificador heredado por porcentajes y el resto del contrato de la API conservan su comportamiento actual.

## Acceptance

- A1: Un acumulador de 2,4 kW y 8 h de carga (19,2 kWh) con 10 h de descarga nominal y 20% de emisión residual entrega como máximo 1,92 kW al 100% de carga y 0,6912 kW al 20%; en un slot de 30 minutos son 0,96 kWh y 0,3456 kWh.
- A2: Una consigna alcanzable con el límite anterior de potencia de carga, pero no con la capacidad de emisión al estado de carga proyectado, devuelve déficit de temperatura y estado `DEGRADED` en vez de `FEASIBLE`.
- A3: Con el acumulador al 100% de carga el plan reproduce el comportamiento previo salvo por el nuevo techo de emisión, y la energía almacenada nunca es negativa ni supera la capacidad.
- A4: Un intervalo sin consigna activa y sin ninguna consigna posterior en el horizonte tiene calor entregado cero; un intervalo sin consigna inmediatamente anterior a una consigna puede entregar calor para cubrir su borde inicial.
- A5: La API expone y persiste las horas de descarga nominal y el porcentaje residual, rechaza cero, valores negativos y porcentajes fuera de rango, y una configuración existente sigue leyéndose tras la migración.
- A6: Los tests cubren por separado la curva del helper, la restricción del optimizador, la puerta de emisión sin consigna y el redondeo de la migración; `make check` pasa.

## Decisions

- D1: Los dos parámetros son características del acumulador y viven en `Heater` (`full_discharge_minutes`, `static_emission_percent`), junto a `power_w` y `full_charge_minutes`, no en `ThermalProfile`, que modela la sala. La API los expone en horas y porcentaje, igual que `full_charge_hours`.
- D2: El suelo residual es un porcentaje de la potencia máxima de emisión y no una potencia absoluta, para no exigir un segundo dato en vatios del fabricante y permitir distinguir estático de dinámico por acumulador.
- D3: El límite usa el estado de carga del borde inicial del intervalo, sin contar la carga de ese mismo intervalo. Es conservador, mantiene la restricción lineal en `stored[i]` y evita añadir binarias al MILP.
- D4: El suelo residual es una capacidad, no una emisión forzada: los límites vigentes de energía disponible siguen aplicándose, así que un acumulador vacío entrega cero.
- D5: R5 restringe la emisión solo en la cola del horizonte, porque cualquier hueco anterior precede a una consigna. Lo que evita una emisión gratuita en los huecos intermedios es el término de calor del objetivo, que solo la usa cuando reduce un déficit; no se añade un parámetro de anticipación.
- D6: Dentro de una ventana con consigna no se cambia la formulación: el peso de confort ya domina al término de calor, así que el optimizador entrega el máximo posible mientras exista déficit y solo lo necesario para mantener el objetivo después.
- D7: Valores por defecto de migración: 600 minutos de descarga nominal y 20% de emisión residual, aplicados a las filas existentes. Cambian el plan de una instalación ya configurada respecto al techo anterior, que es el objetivo del cambio; el operador debe introducir los datos reales de su acumulador.
- D8: El nuevo límite por intervalo se expone en el payload de planificación, pero no se añade una columna a las tablas de detalle del frontend en este cambio.
