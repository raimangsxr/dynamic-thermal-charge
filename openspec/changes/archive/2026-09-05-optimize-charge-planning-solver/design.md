# Design

## Decisions

- Se mantienen las variables `energy` para preservar la serialización y se
  aplican cotas inferiores acumuladas solo hasta 24 horas; para 48 horas se
  conserva el modelo base porque las filas densas empeoran CBC.
- La activación calcula el token actual sin solver y solo reconstruye un
  resultado de un preview durable completado que coincida en revisiones,
  constraints y token. Un payload antiguo o inválido activa el fallback
  normal.

## Risks

- El beneficio depende de la configuración y el hardware; el horizonte
  extendido queda cubierto por benchmark y no se fuerza una optimización que
  aumente su latencia.
- La comprobación de token y revisiones se ejecuta antes de persistir para
  evitar activar planes obsoletos.
