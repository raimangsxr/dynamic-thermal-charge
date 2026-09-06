# Design

## Approach

Un primitivo compartido sustituye a `cursor += timedelta(minutes=slot_minutes)`
en los cuatro generadores de límites. Avanza en **tiempo absoluto** y no en
reloj de pared:

```
next = (current convertido a UTC) + slot_minutes  ->  reconvertido a la zona
```

Los límites resultan monótonos por construcción y cada slot dura exactamente
`slot_minutes` reales. La alineación de pared se conserva porque el salto de
offset de la zona es un múltiplo de `slot_minutes`; para zonas con salto menor
que un slot (Lord Howe salta 30 minutos) el primitivo reencaja hacia delante, lo
que acorta ese slot y es el único caso en que R3 cede ante R1.

## Decisions

- D1: Avanzar en tiempo absoluto y comprobar la alineación de pared, en lugar de
  avanzar en pared y corregir. Es la única de las dos direcciones que garantiza
  monotonía sin casos especiales para hora inexistente y hora ambigua.
- D2: Las claves de diccionario que identifican un slot se normalizan a UTC. Un
  instante local no puede ser clave: dos datetimes de la misma zona con igual
  reloj de pared son `==` y comparten `hash` aunque estén separados una hora por
  un retroceso, así que las dos pasadas de la hora repetida colapsaban en una
  entrada. Descubierto durante la implementación.
- D3: La suma del horizonte sí es una adición de reloj de pared, y es el único
  punto donde eso es correcto: el horizonte se configura en horas de pared.
- D4: No se migra nada. Los planes y el histórico guardan instantes absolutos, y
  un plan anterior sigue siendo interpretable.

## Risks

- **Recuento variable en el MILP.** Un horizonte de 50 slots aumenta las
  variables del problema un 4 % el día del retroceso, dentro del presupuesto de
  tiempo configurable. Cubierto con un test contra el optimizador real.
- **Token de inputs de la preview.** `token_horizon_start` usa `align_to_slot`,
  así que su valor cambia durante la hora repetida y una preview iniciada antes
  de la transición se invalida al activarse. Es el comportamiento que ya existe
  para cualquier cambio de entradas.
