# Política de fallo de relé en el controlador

Status: approved

## Goal

Un relé que no acepta una conmutación no debe impedir que los demás
acumuladores carguen ni tumbar el proceso del controlador. `ChargeController.apply`
conmutaba sin protección: un fallo del driver abortaba el resto de las
transiciones del ciclo, dejaba `_active` divergente del hardware y escapaba de
`ControllerService.run`, que solo captura `KeyboardInterrupt`.

## Requirements

- R1: `apply` intentará todas las transiciones del ciclo. El fallo del driver en
  una salida no impedirá aplicar las restantes.
- R2: `_active` reflejará el estado realmente aplicado: una salida cuyo apagado
  falla permanece activa (se presume cerrada) y una salida cuyo encendido falla
  no se añade. La potencia instantánea y el estado publicados no afirmarán un
  estado que el driver no aceptó.
- R3: Una salida que falló se reintentará en cada ciclo de sondeo posterior. No
  se persistirá ninguna exclusión.
- R4: Mientras alguna salida haya fallado en el último ciclo, el heartbeat se
  publicará con `degraded` verdadero; al aplicarse de nuevo con éxito volverá a
  falso. Cada entrada y salida de esa condición se registrará una sola vez por
  transición, con nivel crítico al entrar.
- R5: Las rutas de `_apply_relay_test` que descartaban el resultado de
  `_sweep_off` harán durable el apagado parcial, como ya exige la spec viva de
  `relay-test`: cualquier fallo parcial arma un bloqueo de seguridad persistente.
- R6: La política de fallo del driver quedará documentada junto a la política de
  fallo del almacén que ya describe `service.py`.

## Outcome

R1-R4 quedan como spec viva en `openspec/specs/controller/spec.md`; R5 añade el
escenario de coordinación perdida a `openspec/specs/relay-test/spec.md`. La
cobertura de rama de `controller.py` pasó del 53 % al 72 %; las rutas de
`_apply_relay_test` preexistentes (`starting`, `ending`, recuperación de
`fault_latched`) siguen sin test.
