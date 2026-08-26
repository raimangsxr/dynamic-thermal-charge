# Specification Quality Checklist: Integración con Home Assistant

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-27
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

Resultado: 16/16, sin marcadores `[NEEDS CLARIFICATION]`. Las cuatro decisiones se cerraron con el
usuario antes de redactar, y **dos de sus respuestas ampliaron el alcance** más allá de lo que se
preguntaba:

- **«MQTT Discovery pero con posibilidad de conectarse a HA vía Wireguard»**. El broker puede no
  estar en la red local, así que la dirección, el puerto y las credenciales son configurables, y la
  resistencia a que el túnel se caiga pasa de detalle a historia de usuario P1 completa (US5). De
  ahí también **FR-010**, la última voluntad: sin ella, un túnel caído dejaría a Home Assistant
  mostrando el último valor conocido para siempre, que es el mismo fallo que las tres fases
  anteriores se dedicaron a evitar.
- **«Sí, con reserva obligatoria»** para el lazo cerrado. Esta es la primera fase desde la 1 que
  **toca el núcleo**: el modelo térmico gana una entrada externa. Por eso los requisitos de reserva
  (FR-024, FR-025, FR-027) están redactados con el mismo rigor que los de AEMET, y por eso
  **FR-023 exige que un acumulador sin temperatura declarada se comporte *exactamente* como
  antes**: la fase no debe cambiar el comportamiento de quien no la use.

Decisiones deliberadas durante la validación:

- **Ni MQTT, ni el nombre del protocolo, ni Home Assistant Discovery se nombran como mecanismo.**
  La spec pide que las entidades aparezcan sin configuración manual (FR-001) y que exista una
  última voluntad que las marque no disponibles al morir el proceso (FR-010). El cómo es de
  `plan.md`.
- **«No disponible» en lugar de nombrar el estado `unavailable`.** Es el tercer estado del
  destino, y la spec lo describe por su efecto.
- **«Un origen de temperatura interior» en lugar de un asunto o una entidad concreta.** El
  mecanismo por el que llega la medida es del plan.

Aportaciones de la redacción que conviene revisar:

- **FR-026: la antigüedad se evalúa con el instante de recepción del dispositivo**, no con uno que
  venga en el mensaje. Es la misma lección de la fase 2 con el latido y de la fase 3 con las
  antigüedades: un reloj ajeno no es una fuente fiable, y aquí un mensaje con fecha manipulada o
  simplemente desfasada haría pasar por reciente una medida vieja.
- **FR-029: una estancia que alcanzó su objetivo pide la carga mínima**, no cero. El mínimo es un
  parámetro que ya existe por acumulador y tiene una razón física: mantener algo de reserva.
- **FR-007: identificadores estables entre reinicios.** Si cambian, las automatizaciones que el
  operador ya escribió dejan de funcionar sin ningún aviso.
- **FR-018: una orden rechazada devuelve la entidad al valor realmente almacenado.** Sin esto,
  Home Assistant se quedaría mostrando el valor que ordenó y que nunca se aplicó, que es la forma
  más silenciosa de mentir en una integración.
- **FR-032: al reconectar se republica el descubrimiento antes del estado.** En el orden inverso,
  Home Assistant recibiría estado de entidades que para él aún no existen y lo descartaría.
- **FR-033: un rechazo de credenciales no se reintenta en bucle apretado.** Es distinto de un
  broker inalcanzable: reintentar cada segundo con una contraseña incorrecta llena registros y
  puede provocar un bloqueo en el broker.
