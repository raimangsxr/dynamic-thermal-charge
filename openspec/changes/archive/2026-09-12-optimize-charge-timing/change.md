# Optimizar el momento de carga y las explicaciones

Status: approved

## Goal

Evitar carga eléctrica anticipada o residual que no contribuya a cumplir las
consignas térmicas previstas, retrasando la carga necesaria hasta el último
momento físicamente viable. Las explicaciones del plan deben conservar y mostrar
los datos reales usados por el optimizador.

## Requirements

- R1: La seguridad eléctrica y la minimización de déficits de confort por
  prioridad siguen dominando cualquier ahorro o desplazamiento de carga; nunca
  se empeora un déficit medible para consumir menos o cargar más tarde.
- R2: Entre planes con el mismo resultado de confort, el optimizador minimiza la
  energía eléctrica cargada y no carga un acumulador cuando la evolución térmica
  prevista sin carga ya cumple todos sus bordes de consigna.
- R3: El precalentamiento fuera de una consigna solo se permite cuando es
  necesario para cumplir su borde inicial; entre soluciones equivalentes, la
  carga se sitúa en los últimos intervalos viables, considerando inercia térmica,
  pérdidas, capacidad de emisión y el límite eléctrico compartido.
- R4: El plan minimiza energía almacenada al final del horizonte que no sea
  necesaria para consignas aún activas o restricciones explícitas de SOC, sin
  introducir una reserva implícita.
- R5: La temperatura exterior se aplica mediante el modelo térmico acoplado; no
  se usa una regla simplificada basada únicamente en comparar exterior y
  consigna.
- R6: Activar una vista previa conserva sin pérdida SOC y temperatura iniciales,
  energía cargada, calor entregado, intercambio térmico, energía y temperatura
  finales, déficit máximo y periodos de carga de cada acumulador.
- R7: `Explicar` y `¿Por qué este plan?` muestran el mismo resumen persistido,
  coherente con el balance por intervalo. Un dato ausente se presenta como no
  disponible y nunca se convierte en cero; un cero medido o calculado sí se
  conserva como tal.
- R8: La explicación relaciona la carga con la siguiente consigna, su instante
  límite, la contribución de la previsión y la energía terminal, permitiendo
  distinguir carga necesaria, anticipada por restricciones y residual.

## Acceptance

- A1: En un caso de Salón con consigna de 22 °C de 15:00 a 23:00 cuya proyección
  sin carga cumple todos los bordes por la evolución meteorológica, el plan
  asigna cero intervalos de carga al Salón.
- A2: Si una consigna requiere carga, dos soluciones con igual confort y energía
  eligen determinísticamente los intervalos más tardíos; solo se anticipan cuando
  la potencia compartida o la dinámica térmica demuestran que los posteriores no
  son viables.
- A3: Ninguna mejora de consumo o horario rebaja el cumplimiento de una consigna
  ni supera los límites eléctricos o físicos existentes.
- A4: Al activar una vista previa con telemetría y balances no nulos, ambos
  botones muestran esos valores y sus totales concuerdan con la serie por
  intervalos antes y después de recargar el proceso.
- A5: Un plan histórico sin evidencia sigue indicando que la información no está
  disponible, sin inventar valores ni alterar sus decisiones guardadas.
- A6: Pruebas repetidas con las mismas entradas producen el mismo plan y cubren
  ausencia de carga, carga tardía, contención eléctrica y round-trip de la
  explicación.
