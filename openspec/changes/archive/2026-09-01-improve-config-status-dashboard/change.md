# Mejorar configuración, estado y carga de reserva

Status: approved

## Goal

Simplificar la edición de acumuladores y corregir la interpretación visible y efectiva de los porcentajes de carga. Convertir Estado en un dashboard útil para la operación diaria y hacer que la configuración MQTT muestre únicamente los campos aplicables a su modo.

## Requirements

- R1: La edición de un acumulador se realizará con un único botón de guardado y una única petición que incluya todos sus campos editables, usando la revisión optimista actual; no se mostrarán botones de guardado por parámetro.
- R2: La configuración de reserva de cada acumulador se editará como porcentaje de 0 a 100. El planificador calculará el tiempo equivalente como `full_charge_minutes * (target_charge + reserve_percent / 100)`, permitiendo superar el 100% equivalente; por ejemplo, 8 horas y 25% de reserva requieren 10 horas equivalentes.
- R3: El campo de porcentaje de las constraints se mostrará y editará como 0–100%, convirtiéndolo al formato interno 0–1 al comunicarse con la API.
- R4: Estado mostrará un dashboard priorizado con salud y frescura del controlador, potencia confirmada, acumuladores en carga/reposo, cumplimiento o déficit del plan, telemetría disponible y previsión; mantendrá las reglas existentes de no afirmar potencia o carga actual cuando el estado no sea actual.
- R5: En MQTT, el interruptor `enabled` siempre será visible; con MQTT activado se mostrarán los parámetros de conexión y credenciales del broker y se ocultarán los valores fijos; con MQTT desactivado se mostrarán los valores fijos y se ocultarán los parámetros y credenciales de conexión.

## Acceptance

- A1: Guardar una edición completa de un acumulador produce una sola petición HTTP, conserva todos los valores enviados y deja el formulario intacto con un mensaje de error si la petición falla.
- A2: La interfaz acepta una reserva de 25% y el planificador genera 10 horas equivalentes para un acumulador de carga completa en 8 horas, sin déficit artificial por superar 100%.
- A3: Una constraint de 25% se presenta como `25` en pantalla y se envía como `0.25` a la API; los valores 0 y 100 son válidos y 101 no lo es.
- A4: El dashboard expone de un vistazo los indicadores operativos definidos en R4 y los tests existentes de estado no actual siguen sin mostrar cifras o estados actuales no confirmados.
- A5: Los tests de configuración MQTT verifican ambos modos y que los campos ocultos no se incluyen en la edición visible; `make check` termina correctamente.
