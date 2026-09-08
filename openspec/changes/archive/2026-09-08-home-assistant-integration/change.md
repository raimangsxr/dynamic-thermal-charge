# Integración nativa con Home Assistant

Status: approved

## Goal

Exponer `dynamic-thermal-charge` como un sistema de calefacción local configurable en Home Assistant, manteniendo en el backend toda autoridad sobre configuración, telemetría, consignas, forecast, planificación y actuación física. Home Assistant solo consulta y ordena cambios mediante una API genérica autenticada.

## Requirements

- R1: La API autenticada debe publicar un identificador estable de instalación y snapshots coherentes del sistema, inventario dinámico, telemetría actual, plan activo y forecast con timestamps reales, sin DTOs acoplados a Home Assistant.
- R2: El backend debe persistir `automatic_control_enabled`. Desactivarlo invalida el plan activo y ordena apagar todas las salidas en el siguiente ciclo del controlador; activarlo solicita un recálculo inmediato. El controlador y la calefacción no dependen de Home Assistant.
- R3: Cada acumulador debe aceptar `AUTO` y `OFF`: `AUTO` lo incluye en el planner y `OFF` lo excluye, solicita replanificación y apaga su salida en el siguiente ciclo. No existirá modo `HEAT` ni control de trampilla en V1.
- R4: La temperatura objetivo mostrada debe ser la consigna semanal activa del backend. Cambiarla modifica atómicamente solo ese intervalo y solicita replanificación; sin intervalo activo se publica sin objetivo y el comando se rechaza de forma explícita.
- R5: El backend debe exponer por acumulador temperatura interior, SOC térmico, carga confirmada, potencia instantánea, posición opcional de trampilla, próxima carga y SOC objetivo siguiente. La trampilla será telemetría opcional de solo lectura y nunca una orden.
- R6: El plan debe exponer intervalos ordenados con acumulador, inicio y fin y, cuando existan, SOC inicial/objetivo y energía planificada. El forecast completo permanecerá accesible por operación específica y no se convertirá en entidades ni atributos grandes.
- R7: `custom_components/dynamic_thermal_charge` debe ofrecer ConfigFlow UI con host, puerto y token, validar credenciales/conectividad, impedir duplicados mediante el identificador estable del backend y soportar reconfiguración y reautenticación.
- R8: Cada entrada debe crear un dispositivo Controller y uno por identificador estable de acumulador, enlazados mediante `via_device`, conservándolos al renombrar y permitiendo Areas. Debe añadir y retirar dispositivos/entidades al cambiar el inventario autoritativo.
- R9: El Controller debe tener exactamente estado, control automático, recálculo, potencia total y calendario global; cada acumulador, Climate, temperatura, SOC sin clase battery, charging, potencia, trampilla, próxima carga y próximo SOC objetivo, con IDs estables, clases/unidades correctas y traducciones.
- R10: V1 debe usar I/O asíncrono y un snapshot REST coordinado con polling moderado, refresco inmediato tras comandos y reintentos automáticos. Un fallo de transporte o snapshot marca todas las entidades unavailable sin presentar datos antiguos; la recuperación las restaura sin recarga manual ni ruido repetitivo en logs.
- R11: El calendario global debe agrupar slots contiguos del mismo acumulador como eventos ordenados, con extremos timezone-aware y resumen de evolución de SOC cuando esté disponible.
- R12: Diagnósticos y logs deben ocultar token y credenciales. README debe documentar instalación, configuración, semántica y limitación de polling de V1.

## Acceptance

- A1: Una ConfigEntry válida crea el Controller y cualquier número de acumuladores con todas las entidades V1; setup, unload, reload, renombre, alta y baja preservan los registros correctos.
- A2: Los estados, unidades, disponibilidad y eventos de calendario corresponden a snapshots backend frescos; forecast y curvas no aparecen en Recorder mediante entidades o atributos masivos.
- A3: Cambiar control automático, modo o consigna activa, y pulsar recálculo, persiste la orden en backend, provoca el efecto confirmado y actualiza Home Assistant; los conflictos y la ausencia de consigna activa se informan sin escritura parcial.
- A4: Caída y recuperación del backend producen unavailable y reconexión automática, mientras un reinicio o ausencia de Home Assistant no altera la operación autónoma del backend.
- A5: Las pruebas cubren API/modelos/migración, setup y ConfigFlow, discovery dinámico, estados, comandos, calendario, availability, reconnect y unload/reload; `make check` termina correctamente.

## Outcome

Implementado el contrato REST operativo autenticado, el control durable en backend y la integración `custom_components/dynamic_thermal_charge` con ConfigFlow, coordinador, discovery dinámico, entidades, calendario, diagnósticos y documentación. Verificado con `make check`.
