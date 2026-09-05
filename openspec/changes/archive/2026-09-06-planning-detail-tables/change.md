# Tablas de detalle para la planificación activa

Status: approved

## Goal

Reducir el scroll de la pestaña Planificación activa manteniendo sus gráficas como
resumen visual y llevando el detalle tabular a diálogos dedicados. El operador
podrá consultar cada serie con una tabla compacta y legible sin mezclarla con la
vista general del plan.

## Requirements

- R1: La pestaña Planificación activa mantiene las cuatro gráficas y elimina de
  sus tarjetas las tablas de detalle renderizadas en línea.
- R2: El botón “Ver detalle” de cada gráfica activa abre un diálogo accesible que
  contiene únicamente la tabla correspondiente a esa gráfica, usando los datos
  del plan activo y sin ningún elemento `canvas` ni gráfica adicional.
- R3: La tabla de temperatura muestra el intervalo, una columna de temperatura
  estimada por acumulador y la temperatura exterior; la tabla de carga muestra
  el intervalo, la potencia de cada acumulador y el total; la tabla agregada
  muestra total, carga base y ambos límites; la tabla acumulada muestra el
  intervalo y el SOC de cada acumulador.
- R4: Los diálogos de detalle tabular usan prácticamente todo el ancho disponible
  del viewport, con una anchura máxima equivalente al doble de la configuración
  máxima anterior, y las tablas aprovechan ese espacio con filas compactas. El
  scroll horizontal, si es necesario por el número de acumuladores, queda
  confinado a la tabla y no al resto de la vista.
- R5: Se conserva la información y el comportamiento de los diálogos de resumen,
  previsión meteorológica y vista previa; el cambio de tablas afecta únicamente
  a los detalles de las gráficas de Planificación activa.

## Acceptance

- A1: Los cuatro `section` de gráficas activas no contienen tablas inline y
  siguen mostrando su gráfica y su botón “Ver detalle”.
- A2: Cada botón de detalle activo abre un diálogo `planning-table` con el título,
  cabeceras y filas de su serie; el diálogo no contiene `canvas`.
- A3: La tabla de detalle usa la primera columna como cabecera de fila, conserva
  los valores de todos los intervalos visibles y representa valores ausentes como
  “sin dato” cuando corresponde.
- A4: La configuración del diálogo tabular es viewport-bound y tiene una
  anchura máxima de `192rem` con `maxWidth` de `98vw`; los diálogos existentes
  fuera de las gráficas activas mantienen sus anchuras y contenido actuales.
- A5: Las pruebas del frontend cubren la ausencia de tablas inline, el contenido
  de los cuatro diálogos tabulares y la ausencia de gráficas en ellos; el build
  del frontend y `make check` pasan.
