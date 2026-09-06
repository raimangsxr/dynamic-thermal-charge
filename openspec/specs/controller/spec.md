## Purpose

Ejecutar el plan de carga sobre las salidas físicas sin atribuirse nunca un
estado que el driver no haya aceptado, y sin que el fallo de una salida afecte a
las demás.

## Requirements

### Requirement: Degradación por salida ante un fallo del driver

El fallo del driver al conmutar una salida degrada únicamente esa salida. El
controlador aplica el resto de las transiciones del ciclo, reintenta la salida
fallida en cada sondeo posterior y no persiste ninguna exclusión. El proceso no
termina por este motivo.

Mientras alguna salida rechace su orden, el controlador se publica como
degradado y el fallo se registra con nivel crítico una sola vez por transición,
no una vez por ciclo.

#### Scenario: Una salida no acepta su conmutación

- **WHEN** el driver rechaza la conmutación de una salida en un límite de slot
- **THEN** las demás salidas aplican su transición y el proceso sigue iterando

#### Scenario: Recuperación de la salida

- **WHEN** una salida que había fallado vuelve a aceptar una orden
- **THEN** el controlador deja de publicarse como degradado y lo registra una sola vez

### Requirement: El estado publicado no excede lo que el driver aceptó

El controlador solo considera activa una salida cuyo estado haya sido aceptado.
Una salida cuyo apagado falla se sigue considerando cerrada; una salida cuyo
encendido falla no se considera activa. La potencia instantánea se deriva de esa
creencia, de modo que nunca afirma un estado no confirmado por el driver.

#### Scenario: Apagado rechazado

- **WHEN** una salida no acepta el apagado
- **THEN** permanece contabilizada como activa y su potencia se sigue imputando
