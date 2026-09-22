# Design

## Durable decisions

- La equivalencia se comprueba sobre resultados canónicos y el solver conserva el orden determinista de variables.
- El solver vigente y la compatibilidad heredada tienen fronteras explícitas; runtime no selecciona el modelo heredado automáticamente.
- El frontend conserva un único estado coordinador y delega presentación y series de gráficas a módulos puros.

## Constraints

- Los nombres públicos usados por tests o consumidores internos se reexportarán temporalmente desde su ubicación actual para permitir una migración por pasos.
- Los modelos persistidos, enums, códigos de error y esquemas HTTP no se moverán de forma que cambie su representación serializada.
- El solver continuará siendo puro respecto de FastAPI y persistencia; la adquisición del lease global seguirá fuera del cálculo.
- No se combinará esta extracción con optimización de rendimiento, cambios de objetivo matemático ni limpieza del modelo heredado.

## Risks

- Una extracción puede alterar el orden determinista del modelo MILP. Se mitigará comparando planes canónicos y manteniendo creación y orden de variables sin cambios.
- Reexportaciones prolongadas pueden convertirse en otra API permanente. Se inventariarán y retirarán dentro del mismo cambio cuando no tengan consumidores.
- Dividir el frontend puede duplicar estado asíncrono. El coordinador seguirá siendo la única autoridad sobre revisión, token y trabajo activo.
