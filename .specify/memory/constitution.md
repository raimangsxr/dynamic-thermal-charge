<!--
Sync Impact Report
==================
Version change: TEMPLATE (sin ratificar) → 1.0.0
Ratificación inicial: se sustituyen todos los placeholders de la plantilla por
principios derivados del código existente (drivers, controller, service, state,
watchdog, config, weather) y del flujo SDD acordado en CLAUDE.md.

Principios añadidos:
  I.   Seguridad física primero (fail-safe)
  II.  Núcleo puro, hardware y red en los bordes
  III. Configuración validada y explícita
  IV.  Continuidad y degradación observable
  V.   Tests deterministas sin hardware
  VI.  Simplicidad y stdlib primero

Secciones añadidas: Restricciones de plataforma; Flujo de desarrollo (SDD);
Governance.
Secciones eliminadas: ninguna (plantilla vacía).

Plantillas y artefactos dependientes:
  ✅ .specify/templates/plan-template.md — la sección "Constitution Check" es
     genérica ("Gates determined based on constitution file"); no requiere cambios,
     las puertas concretas se instancian por feature.
  ✅ .specify/templates/spec-template.md — sin referencias a principios.
  ✅ .specify/templates/tasks-template.md — sin referencias a principios.
  ✅ CLAUDE.md / AGENTS.md — ya declaran el ciclo SDD como obligatorio.
  ⚠ README.md — no menciona la constitución; pendiente decidir si se enlaza.

TODO diferidos: ninguno.
-->

# Dynamic Thermal Charge Constitution

## Core Principles

### I. Seguridad física primero (fail-safe) — NO NEGOCIABLE

Este software conmuta cargas eléctricas reales. El estado seguro es **OFF** y
toda ambigüedad se resuelve hacia el estado seguro.

- Los drivers de salida MUST inicializar cada salida en OFF antes de aceptar órdenes.
- Ausencia de plan, plan inválido, plan caducado o error de refresco MUST resultar
  en ninguna salida activa; nunca en mantener el último estado por defecto.
- El apagado (`shutdown`/`close`) MUST intentar apagar **todas** las salidas: un
  fallo en una salida se registra y el barrido continúa, nunca se aborta.
- Los ids de acumulador desconocidos en un plan MUST ignorarse y registrarse como
  error, no activarse.
- Un fallo de inicialización del driver MUST liberar el hardware ya adquirido antes
  de propagar el error.

**Rationale:** un relé que queda cerrado por un error de software es un riesgo
eléctrico y de facturación; un relé que queda abierto solo es confort perdido.

### II. Núcleo puro, hardware y red en los bordes

El modelo térmico y el planificador MUST ser funciones deterministas sin I/O.

- Todo efecto externo —GPIO, HTTP, reloj, espera, disco— MUST estar detrás de una
  frontera explícita (`Protocol` o `Callable` inyectable: `OutputDriver`,
  `WeatherProvider`, `DeviceFactory`, `clock`, `wait`, `http_get`).
- El paquete MUST importarse y ejecutarse completo en una máquina de desarrollo sin
  Raspberry Pi: las dependencias de hardware se cargan de forma perezosa dentro del
  driver que las necesita.
- El driver GPIO MUST verificar la plataforma antes de tocar el hardware y fallar con
  un error de dominio (`GpioDriverError`), no con una excepción de librería.

**Rationale:** la lógica de negocio se valida en segundos en cualquier portátil, y el
hardware se sustituye sin reescribir el núcleo.

### III. Configuración validada y explícita

La configuración es contrato, no sugerencia.

- El YAML MUST validarse íntegramente al cargar, con `ValueError` y mensaje accionable
  que identifique la clave ofensora.
- NO se permiten valores por defecto implícitos que alteren comportamiento físico
  (pines, potencia máxima, ventanas de carga): si son necesarios, se declaran y
  documentan.
- Los secretos (p. ej. la API key de AEMET) MUST leerse de variables de entorno
  nombradas en la configuración; nunca se escriben en el repositorio ni en logs.
- El estado persistido MUST ser versionado y su carga tolerante: un fichero corrupto o
  de versión desconocida se descarta con log de error y se trata como "sin plan"
  (ver Principio I).

**Rationale:** un pin mal interpretado o una potencia por defecto silenciosa se paga en
el cuadro eléctrico.

### IV. Continuidad y degradación observable

El servicio está pensado para correr sin supervisión durante meses.

- Un fallo de refresco de plan MUST conservar el plan persistido y reintentar con la
  cadencia configurada; nunca terminar el proceso.
- El plan activo MUST persistirse de forma atómica (escritura a temporal + `os.replace`
  + `fsync`), de modo que un corte de corriente no deje estado a medias.
- La degradación (proveedor secundario, reintento, ausencia de plan) MUST registrarse en
  la transición —al entrar y al salir— no en cada iteración del bucle.
- Toda transición de estado de una salida MUST quedar en el log con id, valor e instante.

**Rationale:** sin observabilidad de las transiciones no hay forma de auditar por qué un
acumulador cargó o no una noche concreta.

### V. Tests deterministas sin hardware

- Toda feature o corrección MUST entrar con tests en `tests/`, en el módulo espejo del
  código tocado.
- Los tests MUST ser deterministas: se inyectan dobles (device factory falsa, `http_get`
  falso, reloj y `wait` controlados). PROHIBIDO un test que requiera Raspberry Pi, red
  real, o que duerma en tiempo real.
- La suite completa (`pytest`) MUST pasar antes de considerar una tarea terminada.
- Los caminos de fallo del Principio I (error de driver, plan ausente, id desconocido,
  apagado parcialmente fallido) MUST tener cobertura explícita.

**Rationale:** el comportamiento crítico es precisamente el de los caminos de error, y
esos no se prueban a mano en una Pi.

### VI. Simplicidad y stdlib primero

- Las dependencias de runtime se mantienen al mínimo. Añadir una dependencia MUST
  justificarse en el `plan.md` de la feature.
- Lo que solo hace falta en el despliegue real (`gpiozero`, `lgpio`) MUST vivir en un
  extra opcional, no en el runtime base.
- Se usan `dataclass(frozen=True)`, `Protocol` y type hints completos; se prefiere la
  estructura de datos inmutable al objeto mutable con estado escondido.
- YAGNI: no se añaden capas de abstracción para necesidades hipotéticas.

**Rationale:** el objetivo de despliegue es una Raspberry Pi 2B; cada dependencia es
peso, superficie de fallo y una actualización que puede romper el arranque.

## Restricciones de plataforma

- Python 3.12 o superior. Runtime: PyYAML. Extra `gpio`: `gpiozero` + `lgpio`.
- Objetivo de despliegue: Raspberry Pi 2B con systemd (`deploy/`). El consumo de CPU y
  memoria del bucle de control debe ser despreciable frente a esa máquina.
- Interfaz de usuario actual: CLI (`dynamic-thermal-charge`) más ficheros YAML. Se prevé
  ampliarla (p. ej. interfaz web, API o persistencia adicional) y hacerlo NO requiere
  enmendar esta constitución. Cualquier interfaz nueva MUST ser un borde según el
  Principio II y MUST NOT activar una salida sin pasar por el controlador fail-safe del
  Principio I.
- Zona horaria y horario de tarifa son datos de configuración, nunca constantes en código.

## Flujo de desarrollo (SDD)

El desarrollo se rige por Spec-Driven Development con SpecKit, tal como detalla
`CLAUDE.md`: `/speckit-specify` → `/speckit-clarify` (si hay ambigüedad) →
`/speckit-plan` → `/speckit-tasks` → `/speckit-implement`.

- El código de `src/` se escribe **únicamente** durante `/speckit-implement`, contra un
  `tasks.md` vigente.
- `plan.md` MUST incluir un Constitution Check que enumere cómo la feature respeta los
  Principios I–VI, o justifique la desviación en la sección de complejidad.
- Ninguna fase se salta ni se reordena; cada una parte de los artefactos de la anterior.

## Governance

Esta constitución prevalece sobre cualquier práctica, costumbre o preferencia expresada
en una conversación suelta. Cuando un prompt y esta constitución entren en conflicto,
gana la constitución hasta que se enmiende explícitamente.

- **Enmiendas:** requieren petición explícita del usuario, edición de este fichero vía
  `/speckit-constitution`, y actualización del Sync Impact Report de la cabecera.
- **Versionado semántico:** MAJOR al eliminar o redefinir un principio de forma
  incompatible; MINOR al añadir un principio o ampliar materialmente una guía; PATCH
  para aclaraciones y correcciones sin cambio semántico.
- **Cumplimiento:** `/speckit-plan` verifica conformidad antes de generar tareas;
  `/speckit-implement` no introduce código que viole un principio sin una desviación ya
  justificada en `plan.md`. Los hooks de `.claude/hooks/` son el recordatorio automático,
  no un sustituto de este documento.
- **Desviaciones:** se documentan en el `plan.md` de la feature con motivo y alcance. Una
  desviación recurrente es señal de que la constitución debe enmendarse.

**Version**: 1.0.0 | **Ratified**: 2026-08-26 | **Last Amended**: 2026-08-26
