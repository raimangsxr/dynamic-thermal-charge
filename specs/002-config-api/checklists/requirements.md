# Specification Quality Checklist: API HTTP de estado y configuración

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

Resultado de la validación: 16/16, sin marcadores `[NEEDS CLARIFICATION]`. Las cuatro
decisiones que habrían generado ambigüedad —topología de procesos, autenticación, control
manual y mecanismo de estado en vivo— se cerraron con el usuario antes de redactar.

Decisiones deliberadas durante la validación:

- **Ni el framework ni el formato de la descripción se nombran.** La spec exige una
  descripción autodescriptiva que coincida con lo servido (FR-042), sin fijar la herramienta;
  eso pertenece a `plan.md`.
- **«Credencial compartida» en lugar de nombrar el esquema de autenticación.** Lo que la spec
  exige es comportamiento verificable: nada se ejecuta sin ella, no se filtra, no se puede
  deducir por tiempo de respuesta, y el arranque se rechaza si falta. El mecanismo concreto es
  del plan.
- **«Consulta periódica» en lugar de nombrar el mecanismo de transporte.** La decisión del
  usuario fue consulta REST, pero la spec se expresa en términos de qué debe poder saber el
  cliente y con qué garantía de vigencia.
- **La variable de entorno sí se menciona de forma genérica** (FR-007, FR-049), igual que en la
  fase anterior: es una restricción de despliegue fijada por el usuario y verificable como
  requisito de seguridad, no una elección pendiente.

Aportaciones de la redacción que no estaban en el enunciado y conviene revisar:

- **Historia 2 completa, en P1.** La deduje de la topología elegida: dos procesos que solo se
  comunican por base de datos significan que la API puede leer una transición vieja y
  presentarla como actual. Un panel que afirma que un acumulador de 2,8 kW está cargando
  cuando no lo está induce decisiones equivocadas sobre la instalación eléctrica. De ahí la
  señal de vida del controlador (FR-014) y la distinción explícita entre estado vigente y
  último estado conocido (FR-015 a FR-019).
- **FR-010, comparación en tiempo constante.** Una credencial comparada de forma ingenua se
  puede deducir midiendo tiempos de respuesta. Es cheap de cumplir y caro de añadir después.
- **FR-011, rechazo de credenciales triviales al arrancar.** Sin esto, un despliegue con el
  fichero de entorno de ejemplo sin editar quedaría escuchando con una credencial vacía.
- **FR-019, saltos del reloj.** La vigencia se calcula comparando instantes; un salto del
  reloj del sistema podría dejar el estado permanentemente vigente, que es el fallo peligroso.
- **FR-041 y SC-009.** Con la base de datos remota, una petición podría quedar colgada
  esperando la red en lugar de responder con un error.

## Revisión de `/speckit-analyze` (2026-08-26)

Análisis de consistencia entre `spec.md`, `plan.md`, `tasks.md`, los dos contratos y la
constitución 1.1.0, teniendo en cuenta la coherencia con la fase 1 ya implementada: **15
hallazgos, todos corregidos. Cero CRITICAL** y ninguna violación de un MUST de la constitución.

Correcciones que afectaron a esta spec:

- **FR-007 decía «toda operación exige credencial» y el contrato eximía la ruta de salud**
  (hallazgo HIGH). Se acotó la excepción y se le dio requisito propio, **FR-052**, que fija qué
  debe y qué no debe revelar. De paso se resolvió lo que estaba sin decidir: `/docs` y
  `/openapi.json` **sí** exigen credencial, porque enumeran la superficie de la API y nadie los
  necesita sin autenticar.
- **FR-047 y SC-011 descansaban sobre un comentario** (hallazgo HIGH). Toda la viabilidad en
  ARMv7 depende de que no reaparezca `uvicorn[standard]`, y un comentario no impide nada. Cerrado
  con una guardia (T002) que falla si vuelven las dependencias prohibidas.
- **FR-014 no exigía la cadencia de sondeo**, de la que depende por completo la derivación de la
  tolerancia de vigencia. Un implementador que siguiera solo la spec habría construido un latido
  insuficiente. Ahora la exige, con la razón escrita.
- **Dos controladores contra la misma base de datos se veían igual que uno sano.** La restricción
  única sobre la fila del latido no impide que dos procesos escriban: hace que se pisen. Dos
  procesos conmutando los mismos relés es un riesgo eléctrico, y el peor resultado posible es un
  panel que muestre normalidad. Nuevo **FR-053**, `runner_id` en el latido, detección por
  `started_at` que retrocede, y aviso en la respuesta de estado. La API señala; no arbitra.
- **La ruta de salud no tenía requisito**: la inventaba el contrato, y era justo la única exenta
  de autenticación. Ahora es FR-052.
- **La migración desde la fase 1 no tenía requisito**, aunque una tarea la probaba. Es la primera
  migración de esquema que se aplicará sobre datos reales del usuario. Ahora es FR-048b.
- **SC-003 solo se verificaba a mano** y **SC-011 no era medible**. El primero gana una
  verificación automatizada (T091); el segundo, las cifras concretas que ya estaban en `plan.md`.
- **FR-044 solo se probaba en negativo**: se comprobaba que la puerta de orígenes está cerrada,
  no que se pueda abrir, y de eso depende el frontend de la fase 3.
- **El cursor de paginación se probaba sin estar definido ni implementado.** Ahora es un par
  `(instante, id)` opaco, definido en `data-model.md` y exigido en la tarea del borde de datos.
  Un desplazamiento numérico habría producido elementos repetidos o saltados al insertarse
  registros entre dos páginas.
- **Una tarea invitaba a un test de tiempos** para verificar la comparación del token. Habría
  sido no determinista, y el Principio V lo prohíbe. Se verifica por inspección del camino de
  código.

Cobertura resultante: 54/54 requisitos funcionales y 12/12 criterios de éxito con al menos una
tarea asociada. `tasks.md` pasa de 112 a 117 tareas.
