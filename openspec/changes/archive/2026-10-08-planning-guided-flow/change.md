# Flujo guiado de planificación

Status: approved

## Goal

Reorganizar el módulo de planificación para que editar, comprobar y activar sea un recorrido guiado y enfocado. Separar la información de consulta y diagnóstico del flujo operativo sin eliminar ninguna capacidad actual.

## Requirements

- R1: `/planificacion` presentará como experiencia principal un flujo secuencial con los pasos `Consignas`, `Comprobar` y `Activar`, mostrando un único paso como contexto activo.
- R2: `Consignas` conservará la edición completa de reglas semanales y no iniciará ningún cálculo hasta que el operador solicite comprobar los cambios.
- R3: `Comprobar` reutilizará el trabajo asíncrono de vista previa actual y resumirá primero si el plan es activable, su causa y la acción siguiente; los problemas se agruparán por causa y mostrarán los acumuladores afectados sin repetir mensajes idénticos.
- R4: `Activar` solo estará disponible cuando la vista previa corresponda al borrador actual y su estado permita activación; conservará la confirmación y las reglas actuales de activación normal y de mejor esfuerzo.
- R5: El plan activo, la previsión meteorológica, las planificaciones recientes y todas las gráficas actuales se moverán a una vista secundaria de solo consulta llamada `Análisis y datos`, accesible desde el módulo pero fuera de los tres pasos.
- R6: `Análisis y datos` conservará los detalles y tablas existentes; cuando una serie no tenga datos mostrará un estado vacío explicativo en lugar de un gráfico vacío.
- R7: Cada paso tendrá una sola acción primaria y una barra de acciones persistente que indicará los cambios sin comprobar, una vista previa desactualizada y el motivo de cualquier acción deshabilitada.
- R8: El nuevo recorrido mantendrá nombres accesibles, orden de lectura y foco visibles, y no producirá desplazamiento horizontal de página en los breakpoints soportados.

## Acceptance

- A1: Al abrir Planificación se muestra el flujo de tres pasos y no aparecen simultáneamente el histórico, la previsión ni las gráficas.
- A2: Editar una consigna marca el borrador como pendiente, mantiene deshabilitada la activación y no llama a la API de vista previa.
- A3: Al comprobar, el progreso y el resultado del trabajo quedan visibles en el paso `Comprobar`; cuatro acumuladores excluidos por la misma causa se presentan como un grupo con cuatro filas identificadas.
- A4: Un resultado no activable explica junto a la acción qué debe resolverse, no renderiza gráficas sin intervalos y permite volver a las consignas o recalcular.
- A5: Un resultado activable permite avanzar a `Activar`, muestra el resumen que se va a aplicar y utiliza las confirmaciones existentes antes de sustituir el plan.
- A6: Cambiar el borrador después de calcular invalida visualmente la vista previa anterior e impide activarla hasta recalcular.
- A7: Desde Planificación se puede abrir `Análisis y datos` y consultar el plan activo, las cuatro visualizaciones actuales, la previsión, las planificaciones recientes y sus detalles.
- A8: Las pruebas del componente cubren navegación entre pasos, estados pendiente/desactualizado, agrupación de problemas, disponibilidad de activación, acceso a análisis y ausencia de gráficos vacíos.
- A9: La vista no presenta desplazamiento horizontal de página en escritorio ni en los breakpoints responsive existentes, y los controles principales son alcanzables y comprensibles por teclado.

## Outcome

La planificación abre en el flujo guiado y mantiene la consulta técnica en `Análisis y datos`, sin cambios de API ni de reglas físicas.
