# Gobernanza SDD (Spec-Driven Development) — NO NEGOCIABLE

Este repositorio trabaja **siempre** en Spec-Driven Development con **SpecKit**.
Aplica a cualquier agente de IA y a cualquier humano, **aunque no se pida
explícitamente en el prompt**. El usuario ya ha dado esta instrucción de forma
permanente: no hace falta volver a preguntarla en cada sesión.

## Flujo obligatorio

Para **toda** feature nueva, corrección de bug, refactor con impacto funcional o
cambio de comportamiento:

1. `/speckit-specify` → crea rama de feature + `specs/<NNN>-<slug>/spec.md`
2. `/speckit-clarify` → si la spec tiene ambigüedades (`[NEEDS CLARIFICATION]`)
3. `/speckit-plan` → `plan.md` + artefactos de diseño
4. `/speckit-tasks` → `tasks.md` ordenado por dependencias
5. `/speckit-implement` → ejecuta `tasks.md`; el código se escribe **aquí**, no antes

Opcionales según el caso: `/speckit-analyze` (consistencia entre artefactos),
`/speckit-checklist` (checklist de calidad), `/speckit-taskstoissues`.
`/speckit-constitution` mantiene `.specify/memory/constitution.md`, que gobierna
plan e implementación.

**Reglas duras:**
- No se edita `src/` sin un `tasks.md` vigente para la feature activa.
- No se salta ni se reordena ninguna fase. Si falta una, se ejecuta primero.
- Cada fase parte de los artefactos de la anterior, no de la conversación.
- Los hooks git de `.specify/extensions.yml` (rama de feature, auto-commit) se
  respetan; están declarados como `auto_execute_hooks: true`.

## Qué hacer si el usuario pide código directamente

No implementes. Responde con el paso SDD que falta y ofrécete a ejecutarlo
(p. ej. «esto necesita spec: lanzo `/speckit-specify` con esta descripción»).
Si el usuario insiste tras la advertencia, es su decisión: hazlo y déjalo dicho
explícitamente en la respuesta.

## Exenciones (no requieren ciclo SDD)

Preguntas y análisis, lectura de código, operaciones git, formato/typos/comentarios,
dependencias y tooling, configuración de `.claude/` o `.specify/`, y documentación
que no cambia comportamiento.

## Cómo se hace cumplir

- `.claude/hooks/sdd-guard.sh` (`UserPromptSubmit`): inyecta este recordatorio en
  cada turno, así que sobrevive a la compactación de contexto.
- `.claude/hooks/sdd-preedit.sh` (`PreToolUse` en `Write|Edit`): convierte en
  confirmación manual cualquier edición de `src/` sin `tasks.md` de la feature activa.
- `AGENTS.md` replica estas reglas para agentes que no leen `CLAUDE.md`.

Desactivar o eludir estos hooks requiere petición explícita del usuario.

<!-- SPECKIT START -->
Plan activo: `specs/004-home-assistant/plan.md` (feature `004-home-assistant`).
Fases anteriores implementadas: `specs/001-config-database/`, `specs/002-config-api/`,
`specs/003-web-panel/`.
Para contexto técnico, estructura del proyecto, decisiones de dependencias y comandos,
leer el plan activo y sus artefactos: `research.md`, `data-model.md`, `contracts/` y
`quickstart.md`.
<!-- SPECKIT END -->
