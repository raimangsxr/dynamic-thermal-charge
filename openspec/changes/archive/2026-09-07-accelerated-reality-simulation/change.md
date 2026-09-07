# Simulación acelerada de planificación

Status: approved

## Goal

Permitir validar rápidamente el comportamiento de la planificación contra una
simulación térmica que avance en tiempo acelerado y haga visible el ciclo de
carga, descarga y recarga de los acumuladores.

## Requirements

- R1: La configuración de simulación debe exponer y persistir una relación
  positiva de segundos reales por hora simulada, con valor predeterminado de
  10 segundos por hora.
- R2: Cada ciclo de simulación debe avanzar temperatura y carga almacenada con
  el tiempo simulado; mientras el acumulador no carga, su descarga debe usar la
  pérdida térmica configurada multiplicada por el `demand_factor` del
  acumulador, y mientras carga debe recuperar SOC según su potencia y tiempo de
  carga configurados.
- R3: La simulación debe publicar telemetría coherente de temperatura, consigna
  y SOC, y conservar una serie acotada de muestras para que la interfaz pueda
  mostrar la evolución sin depender de tablas.
- R4: La interfaz de Planificación debe ofrecer una sección gráfica de
  simulación en tiempo real, visible cuando la simulación está activa, con
  actualización periódica y gráficos de temperatura real frente a objetivo,
  SOC (incluyendo reserva/objetivo) y potencia planificada frente a potencia
  ejecutada.
- R5: La simulación debe tomar el estado de carga indicado por el controlador
  y la telemetría resultante debe volver a entrar en el ciclo normal de
  planificación, de modo que una descarga produzca nuevas necesidades de carga
  y el objetivo térmico siga siendo la prioridad.
- R6: La vista de simulación no debe introducir tablas; debe comunicar estado,
  última muestra y problemas mediante gráficos, leyendas y mensajes accesibles.

## Acceptance

- A1: Con la configuración predeterminada, 10 segundos de reloj producen una
  muestra equivalente a una hora simulada; al cambiar el valor, la relación se
  aplica sin reiniciar el proceso.
- A2: Una prueba con un acumulador en reposo muestra descenso de SOC y
  temperatura proporcional a `demand_factor`; con carga activa muestra la
  recuperación y publica ambos valores por MQTT.
- A3: La planificación recibe las muestras simuladas, recalcula la carga tras
  una descarga y la interfaz refleja el cambio en sus gráficos.
- A4: La pantalla muestra claramente si la simulación está activa, detenida o
  sin telemetría reciente, y no muestra series inventadas cuando no hay datos.
- A5: Las pruebas backend cubren conversión temporal, descarga por factor,
  carga, publicación y realimentación; las pruebas frontend cubren la sección
  gráfica, actualización y estados vacíos/error.
- A6: `make check` pasa.
