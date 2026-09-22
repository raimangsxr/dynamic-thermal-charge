# Coordinación de cambios aprobados

Este documento es el contrato operativo para los tres worktrees del desarrollo
paralelo. Los diez cambios activos tienen `Status: approved`. La coordinación
parte del commit `0118bd1` (`main`) y se integra siempre en `Codex-top`.

## Worktrees y ownership

| Worktree | Rama actual | Línea de trabajo | Cambios asignados |
| --- | --- | --- | --- |
| `Codex-top` | `raimangsxr/Codex-top` | Contratos compartidos, E2E, planificación e integración final | `establish-shared-ui-language`, `add-critical-flow-e2e-gate`, `add-planning-recovery-guidance`, `improve-responsive-planning-editor` |
| `Developer1` | `raimangsxr/Developer1` | Plataforma, seguridad, entrega y refactor de planificación al final | `isolate-compose-worktrees`, `make-delivery-reproducible`, `simplify-access-lifecycle`, `modularize-planning-boundaries` |
| `Developer2-cursor` | `raimangsxr/Developer2-cursor` | Módulos frontend acotados, con revisión de `Codex-top` | `reorganize-operator-configuration`, `localize-actionable-diagnostics` |

`Developer2-cursor` es el worktree que el equipo denomina `Developer2`.

## Orden y paralelismo

Cada línea puede avanzar en paralelo mientras respete sus prerrequisitos y
ownership. El orden de handoff es:

1. **Fundación paralela**
   - `Developer1`: `isolate-compose-worktrees` y `make-delivery-reproducible`.
   - `Codex-top`: `establish-shared-ui-language`.
2. **Primera integración**
   - `Codex-top`: `add-critical-flow-e2e-gate`, incluyendo su integración en
     `make check` una vez estabilizado el `Makefile` de `Developer1`.
   - `Developer2`: `reorganize-operator-configuration`, después de la
     fundación de UI; solo modifica el módulo de configuración y sus pruebas.
   - `Developer1`: `simplify-access-lifecycle`, después de la fundación de UI
     y E2E; mantiene en exclusiva las superficies de autenticación.
3. **Contrato de recuperación**
   - `Codex-top`: `add-planning-recovery-guidance`, después de configuración y lenguaje UI.
   - No iniciar cambios en `planning/**` de frontend mientras se modifica el contrato de recuperación.
4. **Módulos dependientes**
   - `Codex-top`: `improve-responsive-planning-editor`, después de recuperación,
     UI y E2E.
   - `Developer2`: `localize-actionable-diagnostics`, después de recuperación
     y UI; solo modifica Diagnóstico y sus pruebas.
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
- `Codex-top` es el owner de los patrones compartidos, el catálogo de UI,
  `frontend/e2e/**`, `frontend/package.json` y `frontend/package-lock.json`
  para E2E. Mientras se extraen patrones no se editan en paralelo los módulos
  que los consumen. `README.md` se integra únicamente desde `Codex-top`.
- `Developer2` es el único owner de `frontend/src/app/config/**` para la
  reorganización de configuración y, después del contrato de recuperación,
  de `frontend/src/app/diagnostics/**` para el diagnóstico localizado.
- `Developer1` es el único owner de `frontend/src/app/core/auth*`,
  `frontend/src/app/core/login/**`, `frontend/src/app/onboarding/**` y los
  adaptadores backend de acceso para `simplify-access-lifecycle`.
- `frontend/src/app/planning/**` se modifica por fases: recuperación y
  responsive en `Codex-top`, y finalmente extracción en `Developer1`. Nunca
  hay dos de esas fases activas simultáneamente.

Si una tarea requiere un archivo fuera de su zona, se detiene en el worktree,
se registra como dependencia de integración y se solicita el cambio desde
`Codex-top`; no se resuelve editando el archivo en paralelo.

## Alcance para Developer2

`Developer2` trabajará un solo cambio cada vez. Sus tareas son deliberadamente
acotadas a plantillas, estilos, catálogo de presentación y pruebas de
componente en módulos independientes. No se le asignan autenticación,
credenciales, Docker/CI, runner E2E, rutas de planificación, solver,
persistencia ni migraciones. `Codex-top` revisa el diff y las pruebas enfocadas
antes de cada handoff; cualquier necesidad de tocar una ruta compartida se
convierte en una petición de integración, no en una edición local adicional.

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
