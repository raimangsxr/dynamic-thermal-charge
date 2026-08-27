# Contract — Coordinación API/controlador para modo test

**Feature**: `005-relay-test-mode`

## Frontera y autoridades

`RelayTestRepository` es inyectable, traduce excepciones SQL y ofrece operaciones atómicas para
reclamar, renovar, intencionar, activar, confirmar/rechazar, terminar, armar/limpiar latch,
consultar por id y publicar degradación de auditoría.

La API puede reclamar/renovar/intencionar/solicitar fin. El controlador puede activar, confirmar,
terminar y recuperar latch. Ningún otro componente acciona salidas. Las escrituras de
configuración consultan el control singleton en su transacción.

| Dato | Autoridad |
| --- | --- |
| Intención | `relay_test_output.desired_state/command_seq` |
| Estado confirmado | retorno de `OutputDriver` persistido en `confirmed_*` |
| Propiedad | digest de credencial de cliente |
| Exclusión automática | sesión reclamada, latch persistente o latch local |
| Recuperación | `fault_latched/fault_generation` y OFF completo |
| Auditoría degradada | marcador best-effort; nunca autoridad de seguridad |
| Mapping/límite | configuración completa en revisión ligada |

## Ciclo del controlador

Antes de `controller.apply(plan, now)`:

1. Leer control. Si falla y existe sesión/latch local, barrer OFF, mantener latch local y no
   aplicar automático.
2. Reconciliar cualquier latch local no persistido antes de continuar.
3. Con `fault_latched`, barrer OFF todas las salidas del snapshot/configuración. Un fallo rearma e
   incrementa generación. Solo éxito total permite CAS de limpieza. No aplicar automático ese ciclo.
4. Sin sesión ni latch, aplicar plan automático.
5. En `starting`, validar revisión, lease, heartbeat/runner; forzar OFF completo y activar. No
   aplicar plan ese ciclo.
6. En `active`, validar invariantes, límite y snapshot; apagar antes de encender y confirmar por CAS.
7. En `ending` o invariante fallida, intentar OFF en todas las salidas. Con éxito,
   terminal/liberar. Con fallo, terminal `failed`, armar latch y liberar sesión atómicamente.
8. El automático vuelve solo en un ciclo posterior libre y sin latch.

## Contrato del barrido OFF

- Recorre todas las salidas configuradas de la sesión, no solo las supuestamente activas.
- Continúa después de cada excepción y devuelve resultados individuales.
- `confirmed_state=false` solo se escribe para llamadas que retornaron correctamente.
- Cualquier fallo deja esa salida `unknown` y exige latch.
- «Confirmado» significa aceptación por el driver. Una futura realimentación puede producir
  «verificado» detrás de la misma frontera sin cambiar arbitraje.
- La API nunca puede limpiar latch ni ofrecer bypass administrativo.

## Orden y atomicidad

- SQL no permanece bloqueado durante GPIO.
- Confirmación de orden usa CAS sobre `command_seq`; secuencia nueva queda pendiente.
- Limpieza usa CAS sobre `fault_generation`; un fallo nuevo gana a recuperación vieja.
- Límite se evalúa antes de tocar salidas; rechazo conserva conjunto confirmado.
- Terminar + armar latch + liberar `session_id` es una transacción cuando SQL está disponible. Si
  no, latch local bloquea y se reconcilia.
- Reclamar o escribir configuración exige control libre y sin latch en la misma transacción.

## Fallos y auditoría

- Fallo de coordinación: OFF inmediato, latch local y ningún automático.
- Fallo de conmutación/cierre: barrido best-effort completo; nunca confirmar salida fallida.
- Fallo de `relay_test_event`/`output_transition`: log, intento best-effort de
  `audit_degraded`, y continuar; ni siquiera el marcador bloquea seguridad.
- Tras un evento persistido se registra recuperación y se limpia degradación si sigue siendo la
  observada.
- `shutdown` usa el mismo barrido. Si no es completo deja/reconcilia latch; el siguiente arranque
  no reproduce intenciones.

Nunca se infiere OFF por ausencia de fila, timeout, terminal o heartbeat viejo. El panel recibe
`unknown` hasta confirmación y ve si el automático sigue bloqueado.
