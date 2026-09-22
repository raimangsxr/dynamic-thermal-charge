# Barrera E2E para flujos críticos

Status: approved

## Goal
Detectar de forma determinista regresiones funcionales, responsive y de accesibilidad en los recorridos de mayor riesgo antes de aceptar un cambio.

## Requirements
- R1: El proyecto dispondrá de pruebas de navegador reproducibles ejecutables localmente y desde `make check`.
- R2: Las pruebas usarán datos controlados y nunca accionarán relés reales, servicios externos ni credenciales de producción.
- R3: Se cubrirán login/401, diagnóstico de plan inválido, corrección navegable, vista previa y activación segura.
- R4: Se comprobarán 390, 768 y 1280 píxeles, ausencia de desbordamiento horizontal y navegación esencial por teclado.
- R5: Los flujos críticos incluirán comprobaciones automáticas de accesibilidad y fallarán ante infracciones acordadas.
- R6: Los fallos producirán artefactos suficientes para diagnóstico sin almacenar secretos.

## Acceptance
- A1: Una sola orden documentada ejecuta la suite E2E desde un checkout preparado.
- A2: `make check` falla ante una regresión funcional, overflow horizontal o infracción de accesibilidad cubierta.
- A3: La suite no depende de AEMET, MQTT, GPIO ni del estado previo de volúmenes locales.
- A4: Capturas, trazas o informes se generan únicamente al fallar y no contienen tokens.

## Decisions
- D1: Se usará Playwright con un backend/fixture controlado y `axe` para las comprobaciones automáticas de accesibilidad.
- D2: La suite será una barrera selectiva de flujos críticos, no una duplicación de todas las pruebas unitarias.

## Tasks
- [x] T1: Incorporar el runner, fixture aislado y comandos del proyecto.
- [x] T2: Implementar los flujos, viewports y aserciones acordados.
- [x] T3: Integrar la suite en `make check` y documentar su diagnóstico.
