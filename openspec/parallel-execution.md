# Coordinación de cambios aprobados

Este documento es el contrato operativo para los tres worktrees del desarrollo
paralelo. Los diez cambios activos tienen `Status: approved`. La coordinación
parte del commit `0118bd1` (`main`) y se integra siempre en `Codex-top`.

## Worktrees y ownership

| Worktree | Rama actual | Línea de trabajo | Cambios asignados |
| --- | --- | --- | --- |
| `Codex-top` | `raimangsxr/Codex-top` | Contratos de frontend, read models e integración final | `establish-shared-ui-language`, `reorganize-operator-configuration`, `add-planning-recovery-guidance` |
| `Developer1` | `raimangsxr/Developer1` | Plataforma, build, entrega y refactor de planificación al final | `isolate-compose-worktrees`, `make-delivery-reproducible`, `modularize-planning-boundaries` |
| `Developer2-cursor` | `raimangsxr/Developer2-cursor` | Barrera E2E, acceso y módulos de presentación independientes | `add-critical-flow-e2e-gate`, `simplify-access-lifecycle`, `improve-responsive-planning-editor`, `localize-actionable-diagnostics` |

`Developer2-cursor` es el worktree que el equipo denomina `Developer2`.

## Orden y paralelismo

Cada línea puede avanzar en paralelo mientras respete sus prerrequisitos y
ownership. El orden de handoff es:

1. **Fundación paralela**
   - `Developer1`: `isolate-compose-worktrees` y `make-delivery-reproducible`.
   - `Developer2`: `add-critical-flow-e2e-gate`.
   - `Codex-top`: `establish-shared-ui-language`.
2. **Primera integración**
   - Integrar la fundación de UI y la barrera E2E en `Codex-top`.
   - `Codex-top`: `reorganize-operator-configuration`.
   - `Developer2`: `simplify-access-lifecycle`, después de la fundación de UI y E2E.
3. **Contrato de recuperación**
   - `Codex-top`: `add-planning-recovery-guidance`, después de configuración y lenguaje UI.
   - No iniciar cambios en `planning/**` de frontend mientras se modifica el contrato de recuperación.
4. **Módulos dependientes**
   - `Developer2`: `improve-responsive-planning-editor`, después de recuperación, UI y E2E.
   - `Developer2`: `localize-actionable-diagnostics`, después de recuperación y UI.
5. **Refactor estructural**
   - `Developer1`: `modularize-planning-boundaries`, después de E2E, recuperación y el editor responsive.
   - La verificación de equivalencia y la integración de `make check` quedan bajo coordinación de `Codex-top`.

La dependencia no obliga a esperar a toda la línea: un cambio se entrega en
cuanto su contrato esté verificado y el siguiente worktree necesita ese
commit. Las tareas de un mismo cambio pueden mantenerse en pausa en el
handoff indicado sin marcar el cambio como terminado prematuramente.

## Rutas exclusivas

Estas reglas evitan editar el mismo archivo desde dos worktrees activos:

- `Developer1` es el único owner temporal de `Makefile`, `deploy/**`,
  `backend/Dockerfile`, `frontend/Dockerfile`, locks de build, metadatos de
  publicación y workflows de entrega. Ningún otro worktree edita `Makefile` ni
  workflows durante la fundación.
- `Developer2` es el owner de `frontend/e2e/**` y de los cambios en
  `frontend/package.json`/`frontend/package-lock.json` necesarios para E2E.
  La conexión de la suite a `make check` se hace como paso de integración una
  vez estabilizado el `Makefile` de `Developer1`.
- `Codex-top` es el owner de los patrones compartidos y del catálogo de UI;
  mientras se extraen no se editan en paralelo los módulos que los consumen.
  `README.md` se integra únicamente desde `Codex-top`.
- `Codex-top` es el owner temporal de `frontend/src/app/config/**` para la
  reorganización de configuración y de los read models/rutas de recuperación.
- `Developer2` es el owner de `frontend/src/app/core/auth*`,
  `frontend/src/app/core/login/**`, `frontend/src/app/onboarding/**` y los
  adaptadores backend de acceso para `simplify-access-lifecycle`.
- `frontend/src/app/planning/**` se modifica por fases: recuperación en
  `Codex-top`, después responsive en `Developer2` y finalmente extracción en
  `Developer1`. Nunca hay dos de esas fases activas simultáneamente.
- `Developer2` es el owner de `frontend/src/app/diagnostics/**` para el
  diagnóstico localizado, después del contrato de recuperación.

Si una tarea requiere un archivo fuera de su zona, se detiene en el worktree,
se registra como dependencia de integración y se solicita el cambio desde
`Codex-top`; no se resuelve editando el archivo en paralelo.

## Protocolo de handoff

1. Cada worktree trabaja únicamente en su cambio asignado y mantiene sus
   checkboxes `T*` coherentes con el código real.
2. Antes del handoff se ejecutan las pruebas enfocadas del cambio y se deja
   anotado el resultado; no se entrega un worktree con una prueba rota conocida.
3. El handoff es un commit convencional autocontenido. `Codex-top` lo integra
   por cherry-pick en orden de dependencia y ejecuta la verificación de
   integración.
4. Los worktrees no se hacen cherry-pick entre sí. Para recibir una base nueva,
   esperan el commit integrado de `Codex-top` y lo incorporan después de
   cerrar su cambio actual.
5. No se modifican `main` ni los worktrees de validación prunables listados por
   Git.

## Criterio de cierre

Un cambio solo se considera cerrado cuando sus requisitos y tareas están
verificados, su commit ha sido integrado en `Codex-top` y el quality gate
global se puede ejecutar desde la base resultante. El PR y cualquier merge a
`main` quedan para el flujo final, nunca para un worktree de desarrollo.
