# Design

## Durable decisions

- El histórico se captura en buckets UTC de cinco minutos después de aplicar las
  salidas. Los valores derivados de la configuración vigente en ese momento
  (energía almacenada y potencia confirmada) se persisten como hechos
  observados; los campos no frescos permanecen `null`, no arrastran el último
  valor y una clave natural hace idempotente el reinicio.
- Las muestras de calibración mantienen su ciclo de vida separado del histórico
  general. La captura y la retención siguen la política de observabilidad de
  fallo abierto para no impedir el control.
- La API consulta un único alcance por página, con rango máximo de siete días y
  paginación. El backend resuelve el plan gobernante desde la auditoría de
  activaciones y la evidencia persistida del plan: una activación dentro de un
  slot solo rige desde el siguiente borde y nunca crea un slot mixto.
- Las señales históricas (garantía, obsolescencia, motivos y límites) proceden
  de la evidencia persistida; si falta, se exponen como desconocidas y no se
  reconstruyen usando la configuración actual. Un plan retenido sin evidencia
  puede dejar una medida sin proyección.
- El modelo de presentación conserva `null` y huecos, y las tablas HTML
  equivalentes son la representación accesible normativa de las gráficas. El
  refresco con la cadencia de Estado solo está activo mientras `Análisis y
  datos` es visible.

## Historical risks

- Un proceso detenido pierde el bucket que no observó; rellenarlo con el último
  valor confundiría ausencia de observación con cero.
- La resolución del histórico no interpola entre slots del plan: cada punto
  hereda el slot nativo que lo contiene y conserva los valores de borde.
