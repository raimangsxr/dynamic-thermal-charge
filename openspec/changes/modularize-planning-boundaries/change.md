# Modularización de los límites de planificación

Status: approved

## Goal
Reducir el riesgo de modificar la planificación separando dominio, cálculo, compatibilidad, coordinación, API y presentación, sin cambiar ningún comportamiento observable.

## Requirements
- R1: Para las mismas entradas, el planificador producirá los mismos estados, intervalos, explicaciones y decisiones de seguridad que antes de la modularización.
- R2: El modelo energético vigente seguirá siendo el único utilizado por runtime; no se introducirá fallback silencioso al modelo heredado.
- R3: La compatibilidad heredada quedará aislada detrás de una frontera explícita y seguirá disponible para los casos actualmente soportados.
- R4: Coordinación, leases, revisiones, tokens, persistencia de trabajos y serialización HTTP conservarán sus contratos.
- R5: La API pública de planificación y los modelos consumidos por el frontend no cambiarán.
- R6: El frontend separará estado del editor, ejecución de vista previa, presentación de resultados y gráficas sin alterar el flujo visible.

## Acceptance
- A1: Pruebas de caracterización comparan resultados representativos antes y después con igualdad determinista.
- A2: Todas las pruebas de planificación, coordinación, persistencia y API permanecen válidas sin relajar aserciones.
- A3: Un análisis de dependencias confirma que dominio y solver no importan FastAPI, Angular ni detalles de persistencia.
- A4: Vista previa, cancelación y activación mantienen los mismos conflictos y garantías de concurrencia.

## Decisions
- D1: Es un refactor sin cambios funcionales ni migraciones de datos.
- D2: Se realizará después de `add-critical-flow-e2e-gate` y de los cambios que estabilizan el contrato de recuperación.

## Tasks
- [ ] T1: Añadir pruebas de caracterización y fijar las fronteras objetivo.
- [ ] T2: Separar dominio, solver, compatibilidad, coordinación y rutas backend.
- [ ] T3: Separar estado, servicios y presentación del frontend.
- [ ] T4: Verificar equivalencia determinista y el quality gate completo.
