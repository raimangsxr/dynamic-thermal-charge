# Design

## Approach

La modularización será incremental y guiada por pruebas de caracterización. Primero se congelarán casos representativos del solver, validación, explicación, preview, cancelación y activación. Después se extraerán, sin reescribir algoritmos, fronteras backend para modelos de dominio, modelo energético vigente, compatibilidad heredada, validación y orquestación. Las rutas HTTP quedarán como adaptadores finos sobre esos servicios.

El componente Angular de ruta seguirá siendo el punto de entrada, pero delegará acceso API y trabajos de preview, estado del editor, presentación de resultados y gráficas en servicios/componentes enfocados. Cada extracción se integrará y verificará antes de iniciar la siguiente.

## Constraints

- Los nombres públicos usados por tests o consumidores internos se reexportarán temporalmente desde su ubicación actual para permitir una migración por pasos.
- Los modelos persistidos, enums, códigos de error y esquemas HTTP no se moverán de forma que cambie su representación serializada.
- El solver continuará siendo puro respecto de FastAPI y persistencia; la adquisición del lease global seguirá fuera del cálculo.
- No se combinará esta extracción con optimización de rendimiento, cambios de objetivo matemático ni limpieza del modelo heredado.

## Decisions

- El backend se separará por responsabilidad de dominio, no por cada endpoint o clase individual.
- La compatibilidad heredada tendrá un adaptador explícito; runtime no la seleccionará automáticamente.
- Las rutas de lectura, preview y activación podrán dividirse en módulos, pero publicarán un único router con el contrato actual.
- El frontend conservará un único estado coordinador para evitar estados divergentes; los componentes extraídos recibirán datos y emitirán intenciones.
- La equivalencia se comprobará sobre resultados canónicos, no sobre detalles internos como orden de diccionarios o ubicación de símbolos.

## Risks

- Una extracción puede alterar el orden determinista del modelo MILP. Se mitigará comparando planes canónicos y manteniendo creación y orden de variables sin cambios.
- Reexportaciones prolongadas pueden convertirse en otra API permanente. Se inventariarán y retirarán dentro del mismo cambio cuando no tengan consumidores.
- Dividir el frontend puede duplicar estado asíncrono. El coordinador seguirá siendo la única autoridad sobre revisión, token y trabajo activo.
