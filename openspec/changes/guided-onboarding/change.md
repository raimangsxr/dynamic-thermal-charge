# Primeros pasos guiados

Status: draft

## Goal
Que una instalación nueva llegue a funcionar sin que el usuario tenga que descubrir por su cuenta en qué orden configurar cada página. Hoy, tras iniciar sesión, se llega a Estado sin acumuladores ni guía, y el componente de onboarding existente solo cubre la credencial y no tiene ruta.

Depende de `automatic-thermal-calibration` para los pasos de temperatura exterior y estancias.

## Requirements
- R1: Estado muestra una lista no bloqueante de primeros pasos mientras quede alguno obligatorio pendiente o hasta que el usuario la descarte; puede reabrirse desde el menú.
- R2: Cada paso indica si está hecho o pendiente, por qué, y enlaza a la página o sección existente donde se resuelve. Los pasos obligatorios son: acumuladores habilitados con salida configurada; MQTT conectado con telemetría fresca de cada acumulador; clave AEMET y municipio con una previsión obtenida; límites eléctricos revisados; consignas por acumulador; y un plan activo.
- R3: Los pasos opcionales son: salidas físicas GPIO, topic de temperatura exterior, estancias calibradas o estimadas, y correo de alertas.
- R4: El estado de cada paso se calcula en el backend a partir de la configuración y el estado vigentes; solo se persisten el descarte de la lista y la revisión explícita de los límites eléctricos.
- R5: El paso de estancias ofrece iniciar la calibración o abrir el cuestionario de estimación desde la lista.
- R6: Las consignas sin ningún día seleccionado o con inicio igual a fin se señalan en el editor antes de comprobar.

## Acceptance
- A1: Pruebas API: con una instalación vacía todos los pasos obligatorios están pendientes con su motivo; al completarlos uno a uno cambian a hechos.
- A2: Pruebas de Angular: la lista aparece en Estado, enlaza a cada sección, se descarta y se reabre; desaparece sola al completar los obligatorios.
- A3: Pruebas del editor de consignas para días vacíos e inicio igual a fin.
- A4: `make check` pasa.

## Decisions
- D1: Lista de comprobación no bloqueante en lugar de un asistente: reutiliza las páginas existentes y no duplica formularios.
- D2: Los límites eléctricos tienen valores por defecto indistinguibles de una configuración real, así que el paso solo se marca hecho cuando el usuario confirma su revisión.
- D3: El componente de onboarding de credenciales queda fuera de alcance y no se modifica.

## Tasks
- [ ] T1: Endpoint de primeros pasos con su cálculo y persistencia de descarte y revisión de límites; pruebas.
- [ ] T2: Lista en Estado, entrada de menú y enlaces a secciones; pruebas.
- [ ] T3: Accesos a calibración y estimación desde el paso de estancias; pruebas.
- [ ] T4: Validación de días vacíos e inicio igual a fin en el editor de consignas; pruebas.
- [ ] T5: Spec viva del panel o de planificación según corresponda; `make check`.
