# Estado reposado y visible de la vista previa de planificación

Status: draft

## Goal

Hacer que el paso de comprobación distinga con claridad entre reposo, cálculo en curso y resultado disponible. La planificación no debe presentar como actual un diagnóstico de telemetría perteneciente a una preview obsoleta ni mostrar el panel técnico del cálculo cuando no aporta información al operador.

## Requirements

- R1: Solo el paso actualmente seleccionado usa `aria-current` y el relleno/color principal de foco. Los pasos anteriores pueden indicar avance con un tratamiento secundario, pero deben distinguirse visualmente del activo.
- R2: Al entrar en el paso 2 sin un cálculo actual, no se muestran estado `completado`, identificador de trabajo, lista de comprobaciones, incidencias ni el estado vacío del gráfico como si existiera un resultado.
- R3: Mientras la preview esté `queued`, `running` o `cancelling`, el paso 2 muestra únicamente el estado del cálculo, sus comprobaciones y las acciones propias de cancelación/consulta; no mezcla ese estado transitorio con un resultado terminal.
- R4: Cuando una preview terminal contiene resultado, se muestran ese resultado y sus acciones, pero se ocultan el encabezado/hint del trabajo y la lista de comprobaciones del contenido principal.
- R5: Cuando una preview termina en `error`, `cancelled` o `interrupted` sin resultado, se muestra únicamente un resumen breve del desenlace y la opción de volver o recalcular; el panel técnico tampoco permanece desplegado.
- R6: Después de cualquier trabajo terminal, un botón con icono de calculadora situado arriba a la derecha abre por hover, foco o toque un popup accesible con su estado y sus comprobaciones, sin exponer el UUID en el recorrido principal.
- R7: La barra de acciones del paso 2 es un contenedor normal, sin sticky, sombra ni degradado de elevación; como máximo usa una separación lineal del contenido.
- R8: Una preview solo se presenta como resultado actual si su token corresponde a las entradas vigentes de planificación, incluida la telemetría utilizable. Si la telemetría vigente está completa y el resultado persistido afirma que falta, la preview se considera obsoleta y se pide al operador recalcular en lugar de mostrar una incidencia falsa.

## Acceptance

- A1: Las pruebas frontend verifican que al seleccionar Comprobar el botón de Consignas no comparte el relleno principal del paso activo, que solo un botón tiene `aria-current="step"`, y que el panel inicial no contiene texto de trabajo completado ni `p.hint` con un UUID.
- A2: Las pruebas frontend verifican reposo, cálculo activo, resultado terminal y terminal sin resultado: las comprobaciones solo aparecen durante el cálculo y, al terminar, el botón de calculadora expone el detalle mediante hover, foco y toque; sin preview no aparece el estado vacío del gráfico.
- A3: Las pruebas frontend verifican que la barra `check-actions` no usa la clase de elevación/sticky y conserva las acciones aplicables de volver, recalcular y continuar.
- A4: Las pruebas backend verifican que un trabajo inactivo terminado con token de telemetría anterior no se devuelve como `preview_job` actual, aunque siga consultable por su endpoint de detalle, y que un trabajo con entradas vigentes sí se conserva.
- A5: Las pruebas frontend/backend verifican que con telemetría MQTT activa y reciente el resultado de planificación no clasifica los acumuladores como faltos de telemetría únicamente por reutilizar una preview antigua.
- A6: `make check` pasa sin modificar el contrato de seguridad de MQTT ni las pruebas existentes que impiden planificar con MQTT desactivado.

## Decisions

- D1: La validez de una preview persistida se decide con las mismas entradas que usaría un nuevo cálculo; no se corrige el mensaje en la UI ocultando selectivamente déficits de una preview cuyo token ya no es válido.
- D2: El detalle técnico se mantiene disponible bajo demanda después de terminar, pero no forma parte del recorrido principal; el popup no necesita mostrar el UUID del trabajo.
- D3: Invalidar una preview obsoleta no inicia otro cálculo automáticamente; el operador conserva el control mediante Recalcular.
- D4: El trabajo que originó el plan activo puede seguir consultándose como información histórica, pero si su token ya no coincide no se presenta como candidato actual ni recupera incidencias antiguas en el paso 2.

## Tasks

- [ ] T1: Separar en la plantilla y el estado del componente las vistas de cálculo activo, resultado terminal y reposo; añadir el detalle técnico accesible tras el botón de calculadora.
- [ ] T2: Corregir el estilo del stepper y convertir las acciones de comprobación en una barra normal con separación lineal.
- [ ] T3: Validar previews persistidas contra las entradas actuales y cubrir la consistencia de telemetría con pruebas backend y frontend.
- [ ] T4: Ejecutar la verificación determinista del proyecto y la inspección visual del flujo de planificación.
