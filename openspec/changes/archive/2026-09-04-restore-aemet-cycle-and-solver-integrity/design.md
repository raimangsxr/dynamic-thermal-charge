# Design

## Approach

La previsión pasa a obtenerse en un paso común de `refresh_plan`
(`runtime.py:167-254`) que se ejecuta antes de decidir el motor. Ese paso usa
`DailyAemetForecastManager` (`watchdog.py:69-95`), que ya implementa la semántica de un
intento más cinco reintentos horarios y acepta el estado como parámetro; el estado
durable se lee y escribe con `store.planning.forecast_cycle(...)` y
`save_forecast_cycle(...)`, que ya existen y ya se usan desde `_record_forecast_cycle`.
Cuando el ciclo devuelve una previsión nueva se persiste con `history.record_forecast`;
la rama automática sigue leyendo `store.planning.latest_forecast(now)`, de modo que la
base de datos continúa siendo la caché durable y el núcleo puro no cambia de contrato.

El endurecimiento del solver se hace dentro de `MilpChargePlanner._solve`
(`charge_planning.py:284-381`), tomando una instantánea de los valores de las variables
tras cada fase resuelta óptimamente. Como cada fase fija su óptimo con
`objective <= optimum + 1e-7` antes de pasar a la siguiente, la última instantánea es
por construcción factible y respeta todos los niveles de prioridad ya optimizados: es el
plan correcto que publicar cuando una fase posterior agota el tiempo.

## Constraints

- El objetivo de despliegue es Raspberry Pi: no se pueden añadir resoluciones MILP ni
  dependencias nuevas. La instantánea de variables es memoria, no cómputo.
- Las convenciones de persistencia son normativas (`persistence/schema.py:1-30`):
  instantes en UTC naive y cantidades físicas en watts y minutos enteros. La carga base
  se almacena en watts.
- `gate.py` rechaza el arranque ante una revisión de esquema desconocida, así que la
  migración debe añadirse a `KNOWN_REVISIONS` y a `EXPECTED_REVISION`.
- El trabajo en curso sin commitear (simulador MQTT, revisión
  `0010_mqtt_planning_simulation`) toca los mismos ficheros de configuración y esquema.
  Esta revisión se apila sobre la 0010, no la sustituye.

## Decisions

- La cadencia de replanificación se calcula como la primera frontera de intervalo igual o
  posterior a `now + replan_minutes`, reutilizando `_seconds_to_next_slot`
  (`runtime.py:325-328`) como caso de `replan_minutes <= slot_minutes`. Alinear a
  frontera es necesario porque el controlador selecciona el intervalo que contiene el
  instante actual; una replanificación a mitad de intervalo cambiaría las salidas dentro
  de un intervalo ya iniciado.
- `ForecastWatchdog` deja de gobernar la cadencia en el controlador y queda solo para el
  entrypoint `_run_watchdog`. `error_retry_seconds` de `ControllerService` sigue
  derivándose de `watchdog.retry_minutes`, que conserva su significado de reintento ante
  almacén no disponible.
- La rama legada consume la previsión del paso común cuando hay una nueva y, cuando no,
  omite su recálculo y conserva el plan en ejecución. No se reconstruye un
  `OutdoorForecast` desde la base de datos: la ruta legada se retira en el cambio
  siguiente y no merece una capa de compatibilidad nueva.
- Los dos límites de potencia se modelan como dos restricciones independientes por
  intervalo en lugar del `or` actual (`charge_planning.py:291`): la contratada menos la
  carga base, y la de acumuladores. Un `or` no puede expresar dos cotas simultáneas.
- La guarda de GPIO se aplica en `_run_controller` (`runtime.py:113-160`) antes de
  construir el driver, no en el núcleo puro: es una decisión de composición del proceso y
  el planificador no debe conocer el tipo de salida.
- La poda de `forecast_hour` no necesita entrada propia en `RETAINED_TABLES`: su clave
  ajena a `forecast` es `CASCADE` (`persistence/schema.py:476`). Sí requiere verificar que
  las claves ajenas están activas en SQLite, donde no lo están por defecto. `automatic_plan`
  sí necesita entrada propia, y arrastra `automatic_plan_slot` por `CASCADE`
  (`schema.py:404`), mientras `plan_audit` sobrevive con `plan_id` a nulo
  (`schema.py:423`).
- La poda debe proteger el plan automático activo y todo plan cuyo `horizon_end` sea
  futuro, replicando la protección que `prune` ya aplica a `plan.window_end`
  (`persistence/history.py:213-216`), y ampliar la protección de `forecast` para no
  huérfanar una previsión que un `automatic_plan` superviviente aún cita.

## Risks

- Conectar el ciclo diario cambia la frecuencia de consulta a AEMET de cada 180 minutos a
  una vez al día. La previsión horaria cubre más de 48 horas, así que el horizonte queda
  cubierto, pero se pierde el refresco intradía. Se mitiga conservando el refresco manual
  y dejando que un ciclo fallido reintente cada hora; el riesgo real sería el contrario,
  ya que hoy el modo automático no consulta nunca.
- Tratar un valor de variable ausente como fallo puede convertir en `INVALID` planes que
  hoy se emiten silenciosamente vacíos. Es el comportamiento correcto y explícito, pero
  hará visible una indisponibilidad del solver que hasta ahora quedaba oculta tras un
  plan aparentemente óptimo con todas las salidas apagadas.
- Rechazar el arranque con GPIO y telemetría no real puede detener una instalación que
  hoy funcione en esa combinación. Es intencional, y el mensaje crítico debe nombrar la
  opción concreta a corregir.
