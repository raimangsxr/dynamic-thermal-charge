# Design

## Approach

Crear un read-model compartido en backend para el estado operativo que combine
telemetría y confirmaciones del controlador con el `automatic_plan` activo y la
previsión más reciente. El endpoint de histórico expondrá una vista paginada
compatible que combine planes automáticos y legacy con un origen identificable.

En frontend se reutilizarán formateadores y catálogos comunes para estados,
eventos, nombres de acumulador e instantes. La información de la previsión
mantendrá separados origen, último intento, error y próxima ejecución. Los
detalles técnicos seguirán disponibles, pero no serán el texto primario de las
tablas operatorias.

## Constraints

- No cambiar el contrato de seguridad ni activar salidas físicas durante las pruebas.
- No eliminar datos legacy ni hacer una migración destructiva; cualquier cambio persistente debe usar migración.
- Respetar `openspec/specs/planning/spec.md` y `openspec/specs/relay-test/spec.md`, especialmente la prohibición de publicar planes no verificables y la confirmación física de relés.
- Mantener instantes UTC en API/persistencia y aplicar `Europe/Madrid` solo en la presentación según la configuración de la instalación.

## Decisions

- La combinación histórica debe usar un identificador compuesto o un campo `source` para evitar colisiones entre IDs de tablas distintas y permitir cursores deterministas.
- El read-model no hará que Estado vuelva a leer el plan legacy para resumir el plan activo; el legacy solo se usará como compatibilidad histórica o cuando no exista un plan automático.
- La corrección Unicode se validará con bytes y cabeceras/decodificación del proveedor y con una fixture persistida; no se corregirán cadenas ya dañadas mediante sustituciones genéricas.
- El catálogo de UI tratará los códigos canónicos en mayúsculas y los alias legacy en minúsculas como la misma semántica.

## Risks

- Unificar fuentes puede cambiar consumidores que dependan del contrato legacy de `/status`; se mitigará con pruebas de compatibilidad y campos opcionales antes de retirar nada.
- Unir dos historiales puede romper paginación si el cursor no incluye origen e instante; se mitigará con orden `(timestamp, source, id)` y pruebas de inserciones entre páginas.
- Cambios de formato horario pueden afectar al cambio de horario de verano; se mitigará probando instantes en ambas transiciones de `Europe/Madrid`.
