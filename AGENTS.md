# AGENTS.md

Las reglas de trabajo de este repositorio están en [CLAUDE.md](./CLAUDE.md) y son de aplicación obligatoria para cualquier agente de IA.

Resumen imprescindible: este proyecto trabaja **siempre** en Spec-Driven Development con SpecKit. Toda feature, bug o cambio de comportamiento pasa por `/speckit-specify` → `/speckit-clarify` (si hay ambigüedad) → `/speckit-plan` → `/speckit-tasks` → `/speckit-implement`, en ese orden y sin saltarse fases. No se edita `src/` sin un `tasks.md` vigente para la feature activa. Exento: preguntas, análisis, git, formato, tooling y documentación sin impacto funcional.

Lee CLAUDE.md completo antes de actuar.
