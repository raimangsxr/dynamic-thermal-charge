# Design

## Durable decisions

- Una estancia es la identidad térmica uno-a-uno del acumulador y la migración
  conserva los coeficientes existentes; no se introduce una segunda identidad
  asignable.
- La sesión y sus muestras sobreviven reinicios, pero el cierre es terminal y
  elimina las muestras. La aplicación de coeficientes, el aviso y la
  replanificación se coordinan de forma idempotente para tolerar una caída
  entre los almacenes de configuración y aplicación.
- La calibración solo sustituye la carga y descarga del acumulador elegido. La
  seguridad global, la prueba de relés y la autoridad de modo tienen
  precedencia; una reanudación exige entradas frescas y autoridad antes de
  volver a accionar.

## Risks

- El modelo de calor sin medidor independiente puede sesgar estancias con
  descarga no lineal o compuerta no reportada; los umbrales de excitación, la
  validación fuera de muestra y la incertidumbre evitan aplicar ajustes no
  identificables.
- Una caída entre los dos almacenes puede dejar una saga a medio aplicar; la
  fase persistida, la aplicación condicionada y las claves de deduplicación
  hacen recuperable cada frontera.
- Un override defectuoso afecta actuadores reales; la precedencia de seguridad,
  los límites de fase y el apagado antes de reanudar reducen ese riesgo.
