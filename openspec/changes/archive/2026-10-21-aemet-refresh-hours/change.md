# Intervalo de actualización AEMET en horas

Status: approved

## Goal
Hacer que el intervalo de actualización automática de AEMET tenga una única
representación en horas enteras en la configuración, la API, la persistencia y
el planificador, con valor predeterminado de 4 horas y ciclo durable.

## Requirements
- R1: `refresh_hours` es el único nombre y representación canónica del intervalo automático; es un entero estricto positivo y su valor predeterminado es 4.
- R2: La configuración pública y su PATCH, la serialización del dominio y la UI usan `refresh_hours`; rechazan `refresh_minutes`, fracciones, booleanos y valores no positivos sin cambiar la revisión ni el valor anterior. La UI muestra horas con `min=1` y `step=1`.
- R3: La persistencia canónica usa horas (`refresh_hours` en el documento y `watchdog_refresh_hours` en la tabla funcional); el migrador y el importador legado convierten `refresh_minutes`/`watchdog_refresh_minutes` solo cuando son divisibles exactamente por 60 (180 minutos se conserva como 3 horas), sin redondeo silencioso.
- R4: Tras cada consulta AEMET correcta, automática o manual, el sistema toma el instante de finalización con el reloj inyectado y programa/persiste `next_run_at` exactamente a ese instante más `refresh_hours`; una consulta manual sustituye cualquier temporizador anterior.
- R5: Un fallo conserva la última previsión válida, limpia el siguiente refresco, persiste el reintento según `retry_minutes` y proyecta únicamente ese reintento como próximo evento; no expone una hora de refresco antigua o calculada como si hubiera habido éxito.
- R6: El estado del ciclo y su próximo instante sobreviven a reinicios. La primera ancla diaria mantiene la zona horaria local configurada; los intervalos de refresco y reintento son duraciones entre instantes UTC, se almacenan como UTC y se exponen como timestamps con zona.
- R7: Estado, Planificación, configuración del sistema y `POST /api/v1/system/weather/refresh` reflejan el mismo estado durable, distinguiendo `forecast_next_run_kind=refresh|retry` y sus instantes; la respuesta manual correcta usa el nuevo instante exacto y el error manual deja el reintento proyectado.

## Acceptance
- A1: Pruebas de dominio/API/configuración demuestran el valor 4 por defecto, aceptan solo enteros positivos, exponen únicamente `refresh_hours` y rechazan entradas antiguas o fraccionarias atómicamente.
- A2: Pruebas de esquema e importación convierten 180 minutos en 3 horas, abortan sin modificar datos ante minutos no divisibles por 60 o fuentes persistidas en conflicto, y dejan la persistencia canónica sin nombres en minutos.
- A3: Pruebas automáticas con proveedor lento demuestran que el siguiente refresco es exactamente `success_at + refresh_hours`, no `request_started_at + ...`, y que el cálculo no cambia al cruzar DST.
- A4: Pruebas del endpoint manual demuestran que el éxito reinicia el temporizador desde su finalización y que el fallo limpia el refresco anterior, conserva el forecast y publica solo el reintento configurado.
- A5: Pruebas de reinicio y proyección verifican que el ciclo durable, Estado, Planificación y configuración muestran el mismo instante/kind y continúan desde el valor persistido.
- A6: Pruebas de Angular verifican el campo de horas, etiqueta/ayuda sin minutos, paso entero y actualización de la configuración; `make check` pasa.
