# Límites de slot correctos en el cambio de hora

Status: approved

## Goal

Los slots se generan con aritmética de reloj de pared (`cursor += timedelta`),
que en las dos transiciones de horario de verano produce límites incorrectos en
tiempo real: el horizonte se ancla en el pasado, un slot dura 90 minutos reales
contabilizados como 30, y en primavera un slot termina antes de empezar y se
solapa media hora con el siguiente. Ocurre dos veces al año con fecha conocida y
afecta al planificador MILP de producción.

## Requirements

- R1: Los límites de slot seguirán cayendo en múltiplos de `slot_minutes` del
  reloj de pared de la instalación.
- R2: Los límites serán estrictamente crecientes en tiempo real. Ningún slot
  terminará antes de empezar ni se solapará con otro, y ningún instante real del
  horizonte quedará cubierto por más de un slot.
- R3: Cada slot durará exactamente `slot_minutes` de tiempo real.
- R4: El horizonte configurado se interpretará en horas de reloj de pared. Un
  horizonte de 24 horas cubrirá 25 horas reales el día del retroceso y 23 el del
  adelanto, con 50 y 46 slots respectivamente cuando `slot_minutes` es 30.
- R5: `align_to_slot` nunca devolverá un instante anterior al recibido. Durante
  la hora repetida devolverá el siguiente límite de slot que aún no ha pasado en
  tiempo real.
- R6: Los minutos asignados y no cubiertos que se publican reflejarán la
  duración real de los slots ocupados.
- R7: Las dos pasadas de la hora repetida usarán el valor horario de previsión
  de esa hora de pared, mediante un respaldo explícito y no por efecto
  colateral de la comparación de datetimes.
- R8: La comprobación de cobertura continua de previsión aceptará el número de
  slots que el horizonte tenga realmente, en lugar de exigir
  `horizon_hours * 60 // slot_minutes`. Sin cobertura para algún slot del
  horizonte se seguirá sin publicar plan.
- R9: El comportamiento fuera de una transición no cambiará: mismos límites,
  mismo recuento y mismos planes que hoy.

## Outcome

R1-R8 quedan como spec viva en el requisito `Ventana y horizonte operativo` de
`openspec/specs/planning/spec.md`. El primitivo compartido (`advance_real`,
`next_slot_boundary`, `slot_boundaries`) vive en `scheduler.py` y lo usan los
cuatro generadores de límites, incluido el optimizador MILP de producción.

Dos trampas del lenguaje que el diseño no había previsto y que costaron sendas
correcciones: entre dos datetimes con el mismo `tzinfo`, `<` compara relojes de
pared e ignora `fold`, y `==`/`hash` también, de modo que las dos pasadas de la
hora repetida colapsaban en una sola clave de diccionario y `boundary_index`
perdía un slot en silencio. Toda comparación y toda clave se normalizan ahora a
UTC.

La segunda mitad de R7 y D2 se retiró con aprobación explícita del usuario tras
la implementación: exponer la reutilización como campo propio exigía migración
Alembic, esquema de API y frontend, y el valor no está degradado como sí lo está
una interpolación, así que no hay nada de lo que avisar al operador.
