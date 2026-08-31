# Planificación horaria y visualización gráfica

Status: approved

## Goal

Usar la predicción horaria de AEMET para calcular una planificación de carga más ajustada a la temperatura prevista y hacerla comprensible desde una nueva sección del panel.

## Requirements

- R1: El proveedor AEMET consultará `prediccion/especifica/municipio/horaria/{municipio}`, seguirá únicamente la URL HTTPS `datos` devuelta por AEMET y expondrá puntos horarios de temperatura durante el horizonte disponible, hasta 48 horas.
- R2: El dominio conservará un resumen diario y añadirá la serie horaria; los proveedores simulado y fallback generarán una serie horaria determinista para que la planificación siga siendo segura y explicable cuando AEMET no esté disponible.
- R3: En cada recálculo, los acumuladores con perfil térmico calcularán su demanda usando las temperaturas horarias que cubren la ventana; la demanda total seguirá respetando `min_charge`, `max_charge` y la configuración del acumulador.
- R4: El planificador asignará primero los intervalos más fríos de la ventana y, en empates o falta de datos, conservará reglas deterministas de prioridad, demanda restante e identificador; nunca superará la potencia máxima ni asignará intervalos fuera de la ventana.
- R5: La serie horaria utilizada, su origen, el plan, sus intervalos, asignaciones y acumuladores quedarán disponibles mediante un endpoint protegido de planificación actual o próxima; los planes existentes conservarán su compatibilidad histórica.
- R6: El panel tendrá una sección nueva “Planificación” con un gráfico de temperaturas, una vista gráfica por acumulador y una vista compuesta que muestre la potencia agregada frente al límite configurado, además de una tabla accesible equivalente.
- R7: La vista identificará claramente el origen AEMET, simulado o fallback, la ventana, la revisión de configuración y cualquier carga no atendida; si no hay plan o previsión, lo indicará sin inventar ceros ni datos.
- R8: Cada perfil térmico podrá configurar `thermal_loss_c_per_hour` (°C/h). El endpoint y el panel proyectarán exactamente 48 horas desde el plan aceptado, dentro o fuera de la ventana; la reserva acumulada disminuirá sin carga según la pérdida configurada y el delta entre objetivo y previsión.

## Acceptance

- A1: Las pruebas verifican la petición horaria de AEMET, el seguimiento de `datos`, la ausencia de API key en la segunda petición y el rechazo de puntos inválidos o sin temperatura.
- A2: Las pruebas verifican series deterministas simuladas/fallback y el resumen diario derivado de los puntos horarios.
- A3: Las pruebas verifican que un plan con temperaturas distintas prioriza los intervalos fríos y sigue cumpliendo potencia, intervalos, prioridades, límites térmicos y déficit calculado.
- A4: Una migración de aplicación conserva las previsiones existentes y guarda/recupera sus puntos horarios en SQLite y PostgreSQL cuando están disponibles.
- A5: El endpoint de planificación devuelve la serie horaria, el plan actual o próximo, las asignaciones y los datos necesarios de cada acumulador; sin datos devuelve una respuesta válida con ausencia explícita.
- A6: Las pruebas frontend verifican la ruta y navegación nuevas, los tres niveles de visualización, la tabla accesible, los estados sin datos y el aviso de déficit.
- A7: `make check` pasa.

## Decisions

- D1: La demanda térmica total de cada acumulador se calculará con la media de las temperaturas horarias disponibles dentro de la ventana de carga; la temperatura de cada intervalo se usará para ordenar dónde se consume esa demanda.
- D2: Si falta la temperatura de un intervalo pero existe resumen diario válido, ese intervalo usará la media diaria y quedará marcado como dato interpolado/no detallado en la respuesta; una previsión sin ningún dato utilizable seguirá el fallback existente.
- D3: La nueva vista consultará el plan persistido actual y, fuera de la ventana activa, el próximo plan futuro persistido; no creará planes desde el navegador.
- D4: La librería gráfica será Chart.js integrada directamente en Angular, manteniendo una tabla HTML como alternativa accesible y verificable.
- D5: La reserva visual se expresará en minutos equivalentes de carga, comienza en cero al inicio del horizonte y se amortiza por intervalo con `thermal_loss_c_per_hour * horas * delta / delta_de_diseño`, limitada al rango de cero a carga completa. La carga asignada en el plan suma minutos y fuera de ventana no se inventan nuevas cargas.
