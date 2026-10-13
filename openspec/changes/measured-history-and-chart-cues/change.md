# Histórico medido y señales visuales en las gráficas

Status: draft

## Goal
Que el usuario pueda comprobar si el plan se cumple y por qué. Hoy todas las gráficas muestran proyecciones y la telemetría solo guarda el último valor, así que nunca se ve lo medido junto a lo planificado. El cambio persiste una serie medida y la superpone a la planificación en `Análisis y datos`, junto con señales visuales de las situaciones límite.

La temperatura exterior medida depende del topic introducido por `automatic-thermal-calibration`; sin él, esa serie queda vacía.

## Requirements
- R1: El controlador guarda cada 5 minutos de reloj, por acumulador, la temperatura interior, el SOC, la energía almacenada, la salida de carga confirmada, la descarga ordenada y la posición de compuerta, y por instalación la temperatura exterior medida. Una medida ausente o no fresca se guarda como nula, nunca con el último valor.
- R2: Las muestras se borran con `retention_days` como el resto del histórico.
- R3: La API sirve la serie medida por rango e instalación o acumulador, con un rango máximo de 7 días por consulta y sin exponer datos de calibración.
- R4: Para cada slot pasado, la comparación usa la proyección del plan que gobernaba ese slot según la auditoría de activaciones, no el plan vigente.
- R5: `Análisis y datos` superpone lo medido y lo proyectado para temperatura interior, energía almacenada, potencia y temperatura exterior previstas frente a medidas, con una ventana pasada seleccionable de 6, 24 o 72 horas.
- R6: Las gráficas marcan el instante actual, sombrean el tramo hasta `guaranteed_until`, distinguen los puntos de previsión interpolados y una previsión obsoleta, anotan los motivos de carga necesaria, precalentamiento y residual, y señalan los intervalos en los que la potencia agregada alcanza un límite.
- R7: `Análisis y datos` se refresca automáticamente con la cadencia de Estado mientras está visible.
- R8: Cada gráfica conserva su tabla accesible equivalente, que incluye las series medidas y muestra "sin dato" para valores nulos.

## Acceptance
- A1: Pruebas de muestreo: una muestra por acumulador cada 5 minutos alineada al reloj, nula con telemetría caducada y sin duplicados tras reinicio.
- A2: Pruebas de retención y de API: rango, límite de 7 días y paginación.
- A3: Prueba de comparación: tras dos activaciones, los slots pasados se comparan con el plan que gobernaba cada uno.
- A4: Pruebas de Angular: series superpuestas, ventana seleccionable, marcador de ahora, sombreado, previsión interpolada y obsoleta, anotaciones de motivo y de límite, refresco automático y tablas equivalentes.
- A5: `make check` pasa.

## Decisions
- D1: El muestreo cada 5 minutos coincide con el de la calibración para poder compartir el muestreador; el histórico general no contiene las muestras de calibración, que siguen borrándose al terminar la sesión.
- D2: La temperatura exterior medida solo se visualiza y nunca entra en la planificación.

## Tasks
- [ ] T1: Tabla de muestras medidas con migración Alembic, muestreador del controlador y retención; pruebas.
- [ ] T2: Endpoint de serie medida y proyección del plan gobernante por slot pasado; pruebas.
- [ ] T3: Gráficas superpuestas, ventana seleccionable y tablas en `Análisis y datos`; pruebas.
- [ ] T4: Marcador de ahora, sombreado, previsión interpolada y obsoleta, anotaciones de motivo y límite; refresco automático; pruebas.
- [ ] T5: Actualizar specs vivas de planificación; `make check`.
