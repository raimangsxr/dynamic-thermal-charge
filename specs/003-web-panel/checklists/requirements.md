# Specification Quality Checklist: Panel web de estado, configuración e histórico

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-26
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

Resultado: 16/16, sin marcadores `[NEEDS CLARIFICATION]`. Las cuatro decisiones que habrían
generado ambigüedad —cómo se sirve, dónde vive la credencial, alcance de la interfaz y estrategia
de pruebas— se cerraron con el usuario antes de redactar.

Decisiones deliberadas durante la validación:

- **Ni el framework, ni el servidor web, ni el mecanismo de almacenamiento del navegador se
  nombran.** La spec exige comportamiento verificable: que la credencial sobreviva a una recarga y
  no a cerrar la pestaña (FR-002), que un servidor web sirva los ficheros y haga de intermediario
  (FR-038), que el panel se compile fuera del dispositivo (FR-037). El «cómo» pertenece a
  `plan.md`.
- **«Servidor web» en lugar de nombrarlo.** La decisión del usuario fue nginx, pero lo que la spec
  exige es la propiedad que se obtiene: un único origen para el navegador y una API que no
  necesita exponerse (FR-039).
- **«Estado sin confirmar» en lugar de hablar de un campo nulo.** La spec describe qué debe
  percibir el operador; que el mecanismo sea un valor nulo en la respuesta es del contrato de la
  fase anterior.

Aportaciones de la redacción que no estaban en el enunciado y conviene revisar:

- **La historia 2 completa, en P1.** El frontend es el último metro donde se puede perder la
  distinción entre estado vigente y último estado conocido, y es justo donde el operador toma
  decisiones. De ahí **FR-011**: encendido confirmado, apagado confirmado y sin confirmar son
  **tres** estados que no pueden compartir apariencia. Un panel con dos estados colapsaría el
  trabajo de la fase anterior en la última pantalla.
- **FR-036: la distinción no puede depender solo del color.** Un indicador verde/gris es la
  solución obvia y deja fuera a quien no distingue esos colores, en una interfaz que informa sobre
  una instalación eléctrica.
- **FR-016: las antigüedades se derivan de los instantes de la API, no del reloj local.** El
  equipo que muestra el panel y el dispositivo pueden tener relojes distintos, y calcular «hace 3
  segundos» contra el reloj local produciría edades imposibles o negativas.
- **FR-020: confirmación explícita para potencia máxima, pin y nivel activo.** Son los tres campos
  cuyo error se paga en el cuadro eléctrico. El resto se cambia sin ceremonia.
- **FR-030: ante una API caída se conserva lo último mostrado, marcado como no actual.** La
  alternativa —vaciar la pantalla— destruye información útil; la otra —dejarla como estaba— miente.
- **FR-046: el refresco se detiene con la vista en segundo plano.** Una pestaña olvidada
  consultando cada pocos segundos durante días es carga gratuita sobre una Raspberry Pi 2B.
- **FR-041 y SC-011: caché.** Es el fallo clásico de desplegar una aplicación de una sola página:
  el operador actualiza y sigue viendo la versión vieja sin entender por qué.
