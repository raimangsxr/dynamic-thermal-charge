# Límite de tiempo configurable del optimizador

Status: approved

## Goal

Permitir ajustar desde la configuración del sistema el tiempo máximo que el
optimizador dedica a cada planificación, con un valor inicial de 2 minutos.

## Requirements

- R1: La configuración de planificación expondrá y persistirá
  `solver_time_limit_seconds`, con valor por defecto `120` para instalaciones
  nuevas y existentes tras la migración.
- R2: Tanto la preview como la planificación automática usarán ese valor como
  presupuesto total compartido de tiempo del solver, conservando la semántica
  actual de `FEASIBLE`, `DEGRADED` e `INVALID`.
- R3: `Sistema → planning` permitirá consultar y editar el límite, y guardará
  el valor mediante la API de configuración existente.
- R4: El límite será un entero estrictamente positivo; valores inválidos se
  rechazarán sin persistir cambios ni modificar el límite vigente.
- R5: Cada sección de la pantalla `Planificación` que contenga un gráfico
  ofrecerá un botón `Ver detalle` que abrirá un diálogo emergente accesible con
  ese mismo gráfico en formato ampliado y una acción explícita para cerrarlo.

## Acceptance

- A1: Una instalación nueva o migrada devuelve `solver_time_limit_seconds: 120`.
- A2: Una preview utiliza el límite configurado y una solución verificada que lo
  agota sigue siendo `DEGRADED` con `solver_time_limit`.
- A3: La UI carga, muestra y envía el campo al guardar la sección `planning`.
- A4: La API rechaza cero, negativos y valores no enteros, y las pruebas
  backend, frontend y `make check` pasan.
- A5: Los gráficos de preview, planificación aceptada y previsión horaria
  tienen su propio botón `Ver detalle`; cada botón abre el diálogo del gráfico
  correspondiente sin mezclar sus series ni sus datos.
