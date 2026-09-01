# Desactivar MQTT con valores fijos de prueba

Status: approved

## Goal
Permitir instalaciones sin broker MQTT y evitar que el proceso MQTT intente
conectarse cuando la integración está desactivada. En ese modo, el controlador
usará una telemetría global fija, editable desde el panel de configuración MQTT,
para poder probar la planificación sin el montaje final.

## Requirements
- R1: Cuando `mqtt.enabled` sea falso, el proceso MQTT no creará el cliente ni
  iniciará el bucle de red, no publicará y no se suscribirá a ningún tópico.
- R2: El proceso MQTT detectará los cambios de `mqtt.enabled` en caliente:
  iniciará la conexión al habilitarse y detendrá la conexión al deshabilitarse,
  sin reiniciar API ni controlador.
- R3: La sección MQTT del panel mostrará y permitirá editar, como un conjunto
  global para todos los acumuladores, los valores fijos de temperatura,
  temperatura objetivo, carga almacenada y temperatura interior; los mostrará
  solo como valores activos cuando MQTT esté deshabilitado.
- R4: Los valores fijos se validarán con los mismos límites de seguridad que la
  telemetría MQTT: temperaturas entre -50 y 80 °C y carga almacenada entre 0 y
  100 %.
- R5: Mientras MQTT esté deshabilitado, cada cálculo de planificación usará los
  valores fijos globales como telemetría válida y la temperatura interior fija
  como lectura interior disponible; al habilitar MQTT volverá a usar únicamente
  las lecturas recibidas por MQTT.
- R6: La configuración MQTT existente conservará sus valores al alternar la
  integración y el comportamiento actual con MQTT habilitado no cambiará.

## Acceptance
- A1: Una prueba de arranque con MQTT deshabilitado demuestra que no se invoca
  la creación del cliente, `connect_async`, `loop_start`, publicación ni
  suscripción.
- A2: Una prueba de ciclo de configuración demuestra que habilitar y deshabilitar
  MQTT inicia y detiene la conexión sin reiniciar el proceso supervisor.
- A3: La API y el panel MQTT permiten leer y guardar los cuatro valores globales,
  validan los límites y los ocultan de las secciones no relacionadas.
- A4: Una prueba de planificación sin mensajes MQTT demuestra que todos los
  acumuladores reciben telemetría válida y que la lectura interior fija se usa
  en el cálculo; una prueba con MQTT habilitado demuestra que no se aplica el
  fallback fijo.
- A5: La suite backend/frontend y `make check` pasan.

## Decisions
- D1: Los valores fijos son globales y se configuran en la sección MQTT del
  panel, no individualmente por acumulador.
- D2: La integración deshabilitada no implica borrar tópicos, credenciales ni
  telemetría persistida; solo cambia la fuente activa de datos y el ciclo de
  vida MQTT.
