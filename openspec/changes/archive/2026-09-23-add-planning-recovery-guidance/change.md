# Recuperación guiada de la planificación

Status: approved

## Goal
Convertir cualquier planificación no utilizable en un diagnóstico coherente y accionable, sin alterar las garantías que mantienen las salidas apagadas cuando no existe un plan válido.

## Requirements
- R1: La API expondrá códigos estables para las causas y acciones recomendadas de un plan no utilizable, además del texto informativo actual.
- R2: Estado y Planificación mostrarán la misma causa principal, causas secundarias y siguiente acción para un mismo estado del sistema.
- R3: La previsión distinguirá datos recibidos, antigüedad, cobertura disponible, cobertura requerida y aptitud para planificar.
- R4: Cada acción soportada llevará directamente a la pantalla o control donde pueda corregirse; las causas sin corrección desde el panel indicarán qué comprobar externamente.
- R5: La ausencia de un plan válido seguirá manteniendo todas las salidas apagadas y nunca habilitará activaciones manuales.

## Acceptance
- A1: Pruebas de API verifican códigos estables para falta de telemetría, cobertura meteorológica insuficiente, configuración inválida y fallo de cálculo.
- A2: Pruebas de componentes verifican que Estado y Planificación presentan la misma remediación para cada código conocido y un fallback seguro para códigos desconocidos.
- A3: Una previsión con resumen diario pero sin puntos horarios se muestra explícitamente como no utilizable.
- A4: Las acciones navegables abren el destino correcto y conservan el contexto de la causa.
