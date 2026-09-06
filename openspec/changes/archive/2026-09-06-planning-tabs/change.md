# Separación por pestañas de la vista de planificación

Status: approved

## Goal

Separar la información operativa de la edición de una planificación y de la previsión meteorológica para reducir la carga visual y evitar confundir el plan activo con una vista previa. La ruta mantendrá una única carga de datos, pero ofrecerá tres ámbitos claramente diferenciados y abrirá siempre en el plan activo.

## Requirements

- R1: La vista de Planificación muestra tres pestañas accesibles tituladas «Planificación activa», «Nueva planificación» y «Previsión meteorológica», en ese orden, y la primera está seleccionada al entrar en la ruta.
- R2: «Planificación activa» muestra únicamente el plan actualmente aceptado por el controlador, sus avisos, resumen y gráficos/tablas accesibles; su contenido no cambia a una vista previa cuando existe un cálculo pendiente o completado.
- R3: «Nueva planificación» concentra la edición de constraints, el cálculo cancelable de la vista previa, su estado, resultado, problemas y las acciones «Descartar» y «Guardar y activar»; no muestra los gráficos del plan activo.
- R4: «Previsión meteorológica» concentra el resumen de la previsión, su gráfico horario, la próxima consulta y el acceso a su detalle; no muestra constraints ni gráficos del plan activo o de la vista previa.
- R5: Cambiar de pestaña conserva el estado de edición, el job y el resultado de la vista previa, y los gráficos del contenido seleccionado se renderizan correctamente al mostrarlo; la representación tabular o de detalle existente sigue siendo accesible.

## Acceptance

- A1: Las pruebas frontend verifican las tres pestañas, el orden, la selección inicial y que el contenido de cada pestaña no incluye los ámbitos de las otras.
- A2: Las pruebas verifican que, con una vista previa disponible, la pestaña activa sigue mostrando los datos del plan aceptado y la pestaña nueva muestra la vista previa.
- A3: Las pruebas verifican que constraints, estado del job, resultado, problemas y activación siguen funcionando desde «Nueva planificación».
- A4: Las pruebas verifican que los gráficos activo, preview y previsión se crean al seleccionar sus pestañas y conservan sus datos actuales, incluidos los valores horarios recibidos.
- A5: `npm test`, `npm run build` y `make check` pasan.
