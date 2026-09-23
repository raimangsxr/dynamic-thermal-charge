# Simplificación del acceso administrativo

Status: approved

## Goal
Mantener un único ciclo de acceso coherente con el despliegue oficial: aprovisionamiento inicial mediante `DTC_API_TOKEN`, autenticación comprobada por la API y recuperación clara cuando la sesión deja de ser válida.

## Requirements
- R1: `DTC_API_TOKEN` será el único mecanismo de aprovisionamiento inicial del token administrativo y se almacenará únicamente mediante su representación no reversible.
- R2: Se eliminarán la API pública, el estado, la credencial temporal y la interfaz específicos de onboarding.
- R3: Una instalación sin un token administrativo persistido no iniciará un modo parcial de onboarding; fallará de forma segura con un error que indique cómo configurar `DTC_API_TOKEN`.
- R4: El login no establecerá la sesión ni navegará a Estado hasta que la API haya aceptado la credencial.
- R5: Una credencial rechazada mostrará un mensaje genérico y permanecerá fuera de `sessionStorage`, logs, URL y estado visible de la aplicación.
- R6: Un `401` durante una sesión borrará la credencial, navegará al login y explicará que la sesión no es válida; un cierre voluntario no mostrará ese error.
- R7: La credencial aceptada seguirá limitada a la pestaña mediante `sessionStorage`, y la rotación administrativa existente seguirá siendo compatible.
- R8: Las instalaciones configuradas conservarán su token persistido y sus datos sin migración destructiva.

## Acceptance
- A1: Un primer arranque con `DTC_API_TOKEN` válido crea una instalación configurada y permite iniciar sesión.
- A2: La inicialización sin token, con un token débil o sin digest persistido termina de forma segura y accionable, sin exponer endpoints de onboarding.
- A3: Una credencial incorrecta no permite observar ninguna pantalla protegida y produce un único mensaje accesible en el login.
- A4: Un `401` sobrevenido limpia la sesión, redirige una sola vez y no genera bucles entre login y una ruta protegida.
- A5: La rotación del token invalida la sesión anterior y permite entrar con el nuevo token.
- A6: Ningún endpoint `/api/v1/onboarding` ni componente o ruta frontend de onboarding permanece en el producto o en su contrato publicado.
