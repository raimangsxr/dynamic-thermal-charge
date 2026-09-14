# Normalizar feedback y dialogos de la interfaz

Status: approved

## Goal
Unificar el feedback transitorio y las confirmaciones para que las acciones sean visibles independientemente del scroll. Aprovechar el espacio disponible en todos los dialogos de contenido sin agrandar los dialogos breves de confirmacion.

## Requirements
- R1: Todo resultado transitorio de una accion iniciada por el usuario, tanto correcto como erroneo, se mostrara mediante un snackbar de Angular Material situado arriba y centrado, y no como texto insertado en una seccion.
- R2: Los snackbars comunicaran visual y semanticamente el tipo de resultado, se cerraran automaticamente tras un tiempo legible y permitiran cierre manual.
- R3: Los errores de validacion asociados a campos o formularios, los indicadores de carga/progreso, los estados vacios y los fallos persistentes que condicionan el contenido o incluyen recuperacion permaneceran en contexto y no se convertiran en snackbars.
- R4: Toda confirmacion existente se presentara en un dialogo modal pequeno y accesible; se eliminaran las confirmaciones renderizadas al final de Configuracion.
- R5: Tambien se pedira confirmacion modal antes de eliminar una consigna del borrador, descartar cambios de planificacion, cancelar una vista previa, guardar y activar un plan, migrar la base de datos, iniciar o finalizar una prueba de reles y solicitar el encendido o apagado de cualquier rele.
- R6: Cancelar o cerrar un dialogo de confirmacion no ejecutara la accion y conservara el borrador o estado previo siempre que corresponda.
- R7: Todo dialogo de contenido o detalle usara una unica anchura maxima responsive compartida, equivalente al mayor formato ya existente (`min(98vw, 192rem)` con `maxWidth: 98vw`); los dialogos de confirmacion conservaran el formato pequeno compartido (`min(28rem, calc(100vw - 2rem))`).
- R8: Los estilos y la configuracion de snackbars y tamanos de dialogo seran compartidos para evitar variantes locales entre pantallas.

## Acceptance
- A1: Al guardar, eliminar, probar una integracion o completar/fallar otra accion, aparece un snackbar arriba y centrado, y no aparece feedback transitorio dentro de la seccion.
- A2: Un error de campo sigue junto al campo; un fallo de carga con contexto o reintento sigue visible en su pagina; el estado de un trabajo en curso sigue en su bloque operativo.
- A3: Cada accion enumerada en R4-R5 queda bloqueada hasta aceptar su dialogo, y cancelar no genera llamadas de mutacion ni pierde cambios locales.
- A4: Los dialogos de explicacion, prevision, planificacion, problemas, fallos, tablas y graficos comparten el formato ancho de R7 y siguen limitados por el viewport en pantallas pequenas.
- A5: Las pruebas de componentes cubren posicion/tipo del snackbar, ausencia del feedback inline, confirmacion/cancelacion de cada familia de acciones y las dos clases de anchura de dialogo.
- A6: `make check` finaliza correctamente.
