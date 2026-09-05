# Visualización de acumuladores y detalle de problemas de planificación

Status: approved

## Goal
Hacer legible la ventana planificada sin recorrer una matriz textual extensa y permitir
que el operador entienda cualquier déficit de una vista previa degradada o inválida.

## Requirements
- R1: La vista previa mostrará una única visualización compacta con múltiples series, una por acumulador, para los intervalos de su ventana planificada, con potencia, energía entregada, porcentaje de capacidad utilizado y SOC.
- R2: La visualización mantendrá una representación tabular accesible con esos mismos valores, pero no obligará al usuario a recorrer una fila horizontal para consultar la planificación.
- R3: Cuando la vista previa tenga uno o más déficits o violaciones, independientemente de que su estado sea `DEGRADED` o `INVALID`, mostrará un botón de detalle.
- R4: El detalle de problemas se abrirá en un diálogo accesible y mostrará todos los problemas encontrados con acumulador, requisito, momento, valores objetivo/proyectado/déficit, causa explicada y acción recomendada cuando exista.

## Acceptance
- A1: Una previsualización con varios intervalos renderiza un único gráfico con una serie por acumulador, limitado a la ventana planificada, y sus datos contienen potencia, capacidad y SOC por intervalo.
- A2: La tabla accesible de cada acumulador contiene los valores de potencia, energía, capacidad y SOC sin depender de una matriz de una sola fila.
- A3: Una previsualización `DEGRADED` con un déficit renderiza el botón de detalle; al activarlo, el diálogo contiene los campos del déficit y no solo el contador.
- A4: Una previsualización sin déficits ni violaciones no muestra el botón de problemas, y una previsualización `INVALID` conserva el detalle existente de sus causas.
- A5: Las pruebas frontend y `make check` pasan.

## Outcome

La vista previa muestra una visualización compacta y tablas por acumulador para
su ventana visible, y ofrece el detalle accesible de todos sus problemas.
