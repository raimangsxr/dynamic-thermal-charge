# Planificación térmica automática por acumulador

Status: approved

## Goal

Sustituir la asignación estática de minutos por una planificación automática e independiente para cada acumulador, coordinada por el límite eléctrico de la instalación. El usuario expresa resultados deseados y el sistema decide cuándo cargar, minimizando energía sobrante sin comprometer el confort ni la seguridad.

## Requirements

- R1: Cada acumulador mantiene su propia telemetría, modelo térmico, constraints y plan; la optimización conjunta solo los acopla para que la potencia total nunca exceda el límite configurado.
- R2: Home Assistant publica para cada acumulador, mediante tres tópicos MQTT configurables, temperatura real en °C, temperatura objetivo en °C y carga almacenada entre 0 y 100 %, aproximadamente cada cinco minutos.
- R3: Una telemetría ausente, inválida o con más de 15 minutos excluye y apaga solamente el acumulador afectado hasta su recuperación, y aparece de forma destacada en Estado.
- R4: El objetivo recibido se considera vigente durante todo el horizonte hasta recibir otro valor.
- R5: El sistema recalcula cada 30 minutos los intervalos futuros, conservando como ejecutado el pasado y usando la telemetría más reciente.
- R6: La granularidad de carga es configurable por instalación entre 5, 10, 15, 20, 30 y 60 minutos, con 30 minutos como valor inicial.
- R7: Cada acumulador admite N constraints recurrentes formadas por porcentaje de carga deseado, hora y días de la semana; puede cargar en cualquier intervalo para cumplirlas.
- R8: El plan usa parámetros térmicos manuales por acumulador y previsión exterior horaria para proyectar la carga almacenada, cuya descarga aumenta con el delta positivo entre temperatura objetivo y real.
- R9: La reserva configurable se aplica por acumulador como carga adicional sobre la necesidad calculada, limitada al 100 % de su capacidad.
- R10: El optimizador minimiza la energía cargada y el exceso térmico, satisface las constraints y la reserva cuando sean factibles, y nunca supera el límite de potencia.
- R11: La previsión AEMET se consulta una vez al día a una hora local configurable para un horizonte configurable, inicialmente 48 horas; tras un fallo hace exactamente cinco reintentos separados una hora.
- R12: Agotados los reintentos, se conserva la última previsión AEMET válida, se marca como obsoleta y se genera un plan conservador que incorpora la reserva configurada; no se sustituye silenciosamente por datos simulados.
- R13: La pantalla de Planificación permite editar constraints, recalcular una vista previa sin alterar el controlador y guardar y activar conjuntamente las constraints y el plan resultante.
- R14: Las constraints inviables se rechazan antes de activarlas mostrando el conflicto; si un cambio posterior vuelve inviable el plan, se activa el mejor plan factible, se avisa inequívocamente del déficit y se preserva el límite eléctrico.
- R15: El panel muestra la previsión AEMET, la matriz temporal por acumulador, temperatura real y objetivo, carga proyectada y requerida, potencia total frente al límite, reserva, constraints y déficits, con alternativa tabular accesible.
- R16: El historial conserva previsiones y su antigüedad, planes y revisiones, constraints aplicadas, telemetría utilizada, intervalos ejecutados, déficits y sus causas, permitiendo explicar al usuario qué ocurrió.

## Acceptance

- A1: Pruebas deterministas demuestran que cada acumulador responde solo a su telemetría y constraints, salvo la coordinación necesaria por potencia.
- A2: Ningún plan, vista previa ni replanificación puede superar el límite configurado.
- A3: Entradas MQTT válidas actualizan el estado y una entrada ausente, inválida o caducada apaga y señala solo su acumulador; la recuperación permite volver a planificarlo.
- A4: El reloj demuestra replanificaciones cada 30 minutos sin reescribir intervalos ejecutados.
- A5: Las constraints recurrentes y la reserva se cumplen cuando existe capacidad; los casos inicialmente inviables se rechazan y los sobrevenidos producen un plan de mejor esfuerzo, aviso e historial explicativo.
- A6: AEMET se consulta en la hora configurada, realiza como máximo una consulta inicial y cinco reintentos horarios, y después utiliza la última previsión real marcada como obsoleta.
- A7: Vista previa no modifica el plan activo; guardar y activar cambia constraints y plan de forma consistente.
- A8: Planificación y Estado presentan los datos, alertas y gráficos definidos, son utilizables en mobile y escritorio y conservan representación accesible sin canvas.
- A9: Desde el historial se puede reconstruir para un intervalo la previsión, telemetría, constraints, decisión, ejecución y causa de cualquier déficit.
- A10: Las migraciones preservan instalaciones existentes y `make check` pasa.
