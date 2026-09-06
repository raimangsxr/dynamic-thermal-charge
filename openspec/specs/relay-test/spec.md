## Purpose

Permitir la comprobación manual y temporal de los relés sin que el panel pueda
atribuirse un estado físico que el controlador no haya confirmado.

## Requirements

### Requirement: Sesión exclusiva y preparada por el controlador

La API solo puede crear una sesión con un heartbeat reciente, un único
controlador y al menos un acumulador habilitado. La sesión permanece en
`starting` hasta que el controlador confirma el barrido de apagado y vuelve a
validar heartbeat, lease y revisión de configuración.

#### Scenario: Controlador no disponible

- **WHEN** se solicita iniciar sin heartbeat reciente o con varios controladores detectados
- **THEN** la API rechaza la operación y no crea ninguna intención de salida

#### Scenario: Preparación confirmada

- **WHEN** el controlador completa el barrido OFF y las invariantes siguen vigentes
- **THEN** activa la sesión y el automático permanece suspendido

### Requirement: Confirmación física y cierre seguro

Una orden aceptada se conserva como pendiente hasta que el controlador la
confirma. Las órdenes no confirmables se muestran como desconocidas. Al
finalizar, el controlador apaga todas las salidas, persiste el resultado de cada
apagado y libera la sesión; cualquier fallo parcial arma un bloqueo de seguridad
persistente.

#### Scenario: Orden pendiente

- **WHEN** el panel solicita cambiar una salida
- **THEN** la tarjeta queda bloqueada y no muestra el nuevo estado como confirmado

#### Scenario: Lease caducado sin órdenes pendientes

- **WHEN** una sesión activa supera su lease
- **THEN** el controlador fuerza el apagado y termina la sesión aunque no haya una orden pendiente

#### Scenario: Apagado parcial

- **WHEN** una o más salidas no aceptan el apagado
- **THEN** esas salidas quedan desconocidas, la sesión falla y el automático permanece bloqueado

#### Scenario: Apagado parcial al perderse la coordinación

- **WHEN** la coordinación deja de ser legible o escribible y el barrido de apagado resulta parcial
- **THEN** el bloqueo de seguridad se hace durable, no solo en memoria del proceso

### Requirement: Consulta operativa y propiedad

Solo la pestaña propietaria puede enviar órdenes, renovar o solicitar el fin.
La consulta expone preparación, actividad, cierre, fallo, disponibilidad del
controlador, auditoría degradada y sesiones terminales con cadencias de sondeo y
renovación configuradas por Operación.

#### Scenario: Sesión terminal

- **WHEN** se consulta una sesión terminada o fallida por su identificador
- **THEN** se conserva el resultado legible y se ofrece iniciar una nueva prueba sin marcar la sesión como activa

#### Scenario: Pestaña observadora

- **WHEN** la consulta no contiene la credencial propietaria
- **THEN** la sesión se muestra en modo solo lectura y ninguna acción se atribuye a esa pestaña

### Requirement: Panel claro y resistente

La pantalla usa la estructura visual de Configuración: cabecera, banners,
paneles, resumen y tarjetas responsive. Sus acciones tienen estados de carga,
evitan solicitudes duplicadas, usan las cadencias recibidas y detienen la
renovación mientras la pestaña está oculta.

#### Scenario: Error conocido

- **WHEN** una orden se rechaza por el límite de potencia o por una condición de coordinación
- **THEN** el panel explica el motivo en lenguaje operativo y propone la siguiente acción
