## Purpose

Ofrecer una integración local y configurable con Home Assistant sin convertirlo en autoridad del sistema térmico. El backend conserva la configuración, la planificación y la actuación; Home Assistant consulta snapshots y emite órdenes autenticadas.

## Requirements

### Requirement: Snapshot operativo autenticado

La API debe publicar un identificador estable de instalación, revisión, salud, inventario dinámico, telemetría fresca y resumen del plan. El forecast completo debe estar disponible mediante una operación separada y no como atributos masivos de entidades.

#### Scenario: Snapshot coherente

- **WHEN** Home Assistant consulta el snapshot
- **THEN** recibe una revisión y `observed_at` comunes para la instalación, acumuladores, telemetría y plan que estén disponibles

### Requirement: Control durable y autoridad del backend

El backend debe persistir el control automático, el modo `AUTO/OFF` de cada acumulador y las generaciones de recálculo. Desactivar el control global o un acumulador debe invalidar su plan y producir salidas apagadas en el siguiente ciclo del controlador; activar o solicitar recálculo debe pedir una nueva planificación.

#### Scenario: Orden concurrente

- **WHEN** una orden usa una revisión obsoleta
- **THEN** la API la rechaza sin escritura parcial y Home Assistant puede refrescar el snapshot antes de reintentar

#### Scenario: Backend autónomo

- **WHEN** Home Assistant está detenido o desconectado
- **THEN** el controlador continúa operando con el estado durable del backend

### Requirement: ConfigEntry y dispositivos estables

La integración debe configurar host, puerto y token mediante ConfigFlow, validar conectividad, rechazar instalaciones duplicadas por UUID estable y soportar reautenticación/reconfiguración. Debe crear un dispositivo Controller y uno por acumulador, enlazados con `via_device`, conservando sus registros al renombrar y reconciliando altas/bajas tras snapshots autoritativos exitosos.

#### Scenario: Inventario dinámico

- **WHEN** un snapshot válido añade o retira un acumulador
- **THEN** Home Assistant crea o elimina únicamente los dispositivos y entidades correspondientes a ese identificador estable

### Requirement: Entidades y disponibilidad coordinadas

El Controller debe exponer estado, control automático, recálculo, potencia total y calendario. Cada acumulador debe exponer Climate `AUTO/OFF`, temperatura, SOC sin clase battery, charging, potencia, trampilla opcional, próxima carga y próximo SOC objetivo. Las lecturas deben usar I/O asíncrono, polling compartido de 30 segundos y actualización inmediata tras órdenes.

#### Scenario: Fallo y recuperación

- **WHEN** falla el transporte o no se obtiene un snapshot válido
- **THEN** todas las entidades quedan no disponibles y no muestran datos antiguos; tras un snapshot válido vuelven a estar disponibles

### Requirement: Calendario de planificación

El calendario global debe fusionar intervalos contiguos del mismo acumulador, ordenar los eventos y exponer fechas con zona horaria y el resumen de evolución SOC/energía cuando exista.

#### Scenario: Slots contiguos

- **WHEN** el plan contiene slots adyacentes del mismo acumulador
- **THEN** el calendario publica un único evento con el intervalo fusionado y su resumen térmico
