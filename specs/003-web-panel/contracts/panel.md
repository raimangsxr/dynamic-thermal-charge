# Contract — Comportamiento del panel

**Feature**: `003-web-panel`

Lo que el panel garantiza al operador. No es una descripción de pantallas: son las reglas que
deben cumplirse en todas ellas.

## La regla que gobierna la vista de estado

> El panel **nunca** presenta como actual algo que la API marca como no vigente.

Concretamente, cuando `controller.state_is_current` es `false`:

| Elemento | Comportamiento obligado |
| --- | --- |
| potencia instantánea | **no se muestra ninguna cifra**. No un cero: un cero afirma que no se consume nada |
| estado de cada salida | se presenta el **último valor conocido**, etiquetado como pasado, con su instante |
| apariencia de ese estado | distinta de la de un estado confirmado, y distinguible **sin color** |
| aviso general | visible, indicando desde cuándo no se ve al controlador |

Las cuatro situaciones del controlador se distinguen y cada anomalía orienta:

| `liveness` | Qué se dice | Qué se sugiere comprobar |
| --- | --- | --- |
| `live` | todo normal | — |
| `live_degraded` | el estado **sí** es actual, pero el controlador no alcanza algo que necesita | la base de datos o el proveedor meteorológico |
| `stale` | no se sabe qué está pasando ahora | si el servicio del controlador está en marcha |
| `never_seen` | el controlador no ha arrancado nunca contra esta base de datos | que el servicio esté instalado y arrancado |

Y si la API informa de **más de un controlador**, la advertencia es prominente y explica el riesgo:
dos procesos conmutando los mismos relés.

## Reglas de la configuración

- Cada escritura envía la revisión leída. Un conflicto se presenta como «la configuración cambió»
  con la acción de releer, **nunca** reintentando solo ni sobrescribiendo.
- Un rechazo con campo identificado se muestra **junto a ese campo**, con el valor anterior aún
  visible.
- `max_total_power_kw`, `pin` y `active_high` exigen confirmación explícita que diga qué cambia.
  Los demás campos, no: pedir confirmación para todo enseña a confirmar sin leer.
- Eliminar un acumulador exige confirmación y avisa de que su histórico se conserva.
- Salir de un formulario con cambios sin guardar avisa antes de descartarlos.
- El panel valida para dar respuesta inmediata, pero **la API es la autoridad**. Nada se relaja
  aquí.

## Reglas de tiempo

- Las antigüedades se toman de la API. **Nunca** se calculan contra el reloj del navegador: los
  relojes del móvil y de la Raspberry Pi pueden diferir, y la Pi no tiene reloj con batería.
- El sondeo se detiene cuando el documento no está visible y se reanuda **de inmediato** al volver
  al frente, no en el siguiente tick.
- Un refresco no pierde la posición de lectura ni el foco.

## Reglas ante ausencias

- API sin responder: se indica, se conserva lo último mostrado marcado como no actual, y no se
  queda cargando indefinidamente ni se vacía.
- Esquema pendiente de intervención: se dice qué ejecutar **en el dispositivo** y que el panel no
  puede hacerlo.
- Credencial rechazada durante el uso: se vuelve a la pantalla de acceso con la explicación, no un
  error técnico.
- Fallo de red a mitad de una edición: se informa de que no se aplicó y el formulario conserva lo
  introducido.

## Lo que el panel no puede hacer

- **No** puede accionar ninguna salida, porque la API no lo permite. Tampoco debe insinuar que
  exista un forzado manual.
- **No** puede migrar el esquema ni inicializar la base de datos.
- **No** guarda la credencial de forma persistente ni la pone en la dirección de la página.
