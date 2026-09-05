# Ventana y horizonte desde el slot actual

Status: approved

## Goal
Corregir las fechas mostradas y calculadas por Planificación para que comiencen
en el slot actual y separar la ventana visible del horizonte completo. Permitir
configurar ambas duraciones desde Sistema → Planificación.

## Requirements
- R1: Toda planificación automática, vista previa y activación debe comenzar
  en el instante de recalculo redondeado hacia abajo al slot configurado; debe
  eliminar segundos y microsegundos.
- R2: El horizonte debe cubrir exactamente la duración configurada desde ese
  inicio y la ventana debe compartir el mismo inicio y terminar según su propia
  duración; la respuesta de Planificación y la vista previa deben mostrar ambas
  fechas separadamente.
- R3: Sistema → Planificación debe permitir editar y conservar
  `planning_window_hours` y `forecast_horizon_hours`, con valores enteros
  positivos de hasta 48 horas y ventana menor o igual que horizonte.
- R4: Los valores por defecto para instalaciones nuevas o existentes sin estos
  ajustes deben ser ventana de 12 horas y horizonte de 24 horas.
- R5: La resolución del solver y las tablas/gráficos del horizonte deben usar
  el horizonte configurado; la proyección de la ventana debe mostrar solo sus
  intervalos iniciales, sin alterar el horizonte completo.
- R6: Si falla cualquier paso del cálculo de una vista previa, el panel debe
  mostrar un enlace o botón para abrir un diálogo emergente con el paso fallido,
  su estado, detalle y error general del trabajo cuando exista.

## Acceptance
- A1: Con `slot_minutes=15` y hora `12:10`, una planificación empieza a las
  `12:00`; con los valores por defecto muestra ventana `12:00–00:00` y
  horizonte `12:00–12:00` del día siguiente.
- A2: Las pruebas verifican que la duración configurada del horizonte produce
  todos sus slots y que la ventana y el horizonte usan el mismo inicio.
- A3: Las pruebas de persistencia y API verifican los defaults, guardado,
  validación ventana ≤ horizonte y lectura de ambos campos.
- A4: Las pruebas del frontend verifican que Sistema → Planificación muestra y
  envía ambos campos, y que Planificación representa ventana y horizonte con
  fechas distintas cuando corresponda.
- A5: Una prueba del frontend verifica que un fallo de cualquier comprobación
  muestra la acción de detalle y que el diálogo contiene el nombre del paso y
  el detalle del error.

## Decisions
- D1: Las duraciones se expresan en horas enteras y se limitan a 48 horas, que
  coincide con el límite existente del planificador.
- D2: La ventana es la proyección visible inicial del plan; el solver y el eje
  temporal de planificación siguen cubriendo el horizonte completo.
- D3: El detalle del fallo se presenta mediante el mismo diálogo accesible de
  Angular Material usado por los detalles de planificación, con cierre explícito
  y cierre mediante Escape.
