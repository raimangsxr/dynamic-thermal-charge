# Pulido de calibración térmica, estado y avisos

Status: approved

## Goal

Hacer coherentes y legibles las vistas de calibración térmica, Estado y Avisos sin alterar el contrato de la API ni los flujos operativos existentes. La interfaz debe mostrar los coeficientes con precisión adecuada, mantener una lectura clara y responsive de los equipos, y ofrecer activación de avisos del navegador compatible con estándares web y degradación accionable.

## Requirements

- R1: Calibración térmica muestra capacidad y pérdida con como máximo dos decimales, redondeados al más cercano; el redondeo es solo visual y conserva sin cambios los valores numéricos enviados y guardados.
- R2: Calibración térmica no muestra un enlace local a la bandeja global de avisos; la navegación global y la página Avisos siguen siendo los puntos de acceso existentes.
- R3: Activar avisos del navegador usa detección y APIs estándar de Web Push, Notification y service worker para completar el flujo existente en Chrome y otros navegadores compatibles, sin etiquetar como `unsupported` una plataforma compatible.
- R4: Cuando el navegador, el contexto, el permiso, la configuración VAPID o la suscripción impidan activar avisos, la interfaz muestra un estado localizado, diferenciado y accionable que explica el siguiente paso; nunca expone el literal técnico `unsupported` al usuario.
- R5: Estado presenta los equipos en una sola fila horizontal en desktop; en viewport móvil permite wrap responsive sin perder nombre, potencia, estado confirmado/no confirmado ni accesibilidad.
- R6: Botones, pestañas y lista de Avisos usan los componentes y patrones de Angular Material ya presentes, conservando las vistas Activas/Histórico, acuse, paginación y las llamadas API actuales.
- R7: Calibración térmica aplica una separación visual mínima de 1 rem en los ejes horizontal y vertical entre la sección de estancias y sus artículos, manteniendo el contenido no adosado a los bordes y legible en móvil.

## Acceptance

- A1: Pruebas de Angular verifican que valores con más de dos decimales se renderizan redondeados al más cercano y que guardar/editar sigue enviando el valor numérico original.
- A2: Prueba de plantilla de calibración confirma que no existe el enlace "Ver la bandeja global de avisos" y que la navegación global a Avisos permanece disponible.
- A3: Pruebas cubren Chrome/estándares compatibles, permiso denegado, APIs ausentes, contexto no apto, clave VAPID ausente y errores de suscripción; ningún caso compatible o degradado muestra `unsupported` y cada fallo ofrece una acción o explicación útil.
- A4: Pruebas de layout/plantilla verifican una fila desktop de equipos, wrap en viewport móvil, controles Material en Avisos y separación mínima de 1 rem en la calibración.
- A5: Las interacciones de Avisos (Activas, Histórico, Acusar y Cargar más) conservan sus peticiones, estados y paginación actuales; no se modifica ningún endpoint.

## Outcome

La implementación verificada conserva los contratos de API y flujo operativo, incorpora la presentación responsive y los controles Material, y traduce la activación Web Push estándar a estados localizados y accionables.
