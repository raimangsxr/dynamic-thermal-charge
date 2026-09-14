# Fecha y municipio de la previsión en Estado

Status: approved

## Goal

Corregir la representación del municipio de AEMET en la sección «Datos de
contexto» y mostrar cuándo se obtuvo por última vez una previsión válida.

## Requirements

- R1: El endpoint de Estado debe exponer `forecast_last_success_at`, con la
  fecha/hora de la previsión AEMET más reciente almacenada correctamente; una
  consulta fallida posterior no debe modificarla y, si no existe ninguna,
  debe ser `null`.
- R2: El municipio mostrado en Estado debe conservar correctamente caracteres
  Unicode como `ñ`, incluyendo valores ya persistidos con la forma mojibake
  `Ã±`.
- R3: La tarjeta «Datos de contexto» debe mostrar «Última consulta correcta» y
  formatear `forecast_last_success_at` con la zona horaria de la instalación,
  manteniendo el estado de consulta, el error y la próxima actualización.

## Acceptance

- A1: Tras registrar una previsión y después un intento fallido, `GET
  /api/v1/status` conserva la fecha/hora de la previsión registrada y expone el
  error/estado del último intento por separado.
- A2: Un municipio `Noia, A CoruÃ±a` se devuelve y se renderiza como
  `Noia, A Coruña` en Estado.
- A3: La pantalla muestra «Última consulta correcta» con la fecha formateada;
  sin previsión correcta muestra el marcador de ausencia existente.
- A4: Las pruebas focalizadas y `make check` pasan.
