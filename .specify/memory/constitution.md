<!--
Sync Impact Report
==================
Version change: 1.0.0 → 1.1.0 (MINOR)

Motivación: enmienda solicitada explícitamente por el usuario, originada por la feature
`001-config-database`, que sustituye la configuración estática en YAML por persistencia en
base de datos (SQLite local o PostgreSQL remoto) y añade histórico auditable. El Principio
III estaba redactado en términos de YAML y habría bloqueado el Constitution Check de esa
feature.

Principios modificados (ninguno renombrado, ninguno eliminado):
  III. Configuración validada y explícita — ampliado: la validación es ahora independiente
       del origen de la configuración; se añaden reglas sobre procedencia de credenciales y
       sobre esquema versionado del almacén de configuración.
  IV.  Continuidad y degradación observable — ampliado: cubre la pérdida de acceso al
       almacén de configuración en caliente y el fallo de escritura de auditoría.
  VI.  Simplicidad y stdlib primero — ampliado: las dependencias de un borde concreto van
       en extras opcionales; el núcleo debe importarse sin ellas.

Principios sin cambios: I (Seguridad física primero), II (Núcleo puro), V (Tests
deterministas sin hardware).

Secciones modificadas:
  Restricciones de plataforma — actualizada: origen de configuración en base de datos,
  PostgreSQL siempre externo al dispositivo, prohibición de cadenas de construcción de Node
  en la Pi, dependencias de persistencia declaradas con su justificación frente al
  Principio VI, y la CLI deja de ser la única interfaz prevista.

Secciones añadidas: ninguna. Secciones eliminadas: ninguna.

Razón del bump MINOR: se amplía materialmente la guía de tres principios y de las
restricciones de plataforma, sin eliminar ni redefinir ningún principio de forma
incompatible. Ninguna regla vigente en 1.0.0 deja de cumplirse en 1.1.0.

Plantillas y artefactos dependientes:
  ✅ .specify/templates/plan-template.md — la sección "Constitution Check" sigue siendo
     genérica ("Gates determined based on constitution file"); las puertas concretas se
     instancian por feature. Sin cambios necesarios.
  ✅ .specify/templates/spec-template.md — sin referencias a principios ni a YAML.
  ✅ .specify/templates/tasks-template.md — sin referencias a principios ni a YAML.
  ✅ CLAUDE.md / AGENTS.md — declaran el ciclo SDD como obligatorio; no referencian YAML
     como origen de configuración. Sin cambios necesarios.
  ⚠ README.md — documenta extensamente la configuración YAML y quedará desalineado hasta
     que se implemente `001-config-database`. Su actualización es un requisito de esa
     feature (FR-031), no de esta enmienda. Sigue pendiente además la decisión de v1.0.0
     sobre enlazar la constitución desde el README.

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

- Todo efecto externo —GPIO, HTTP, base de datos, reloj, espera, disco— MUST estar detrás
  de una frontera explícita (`Protocol` o `Callable` inyectable: `OutputDriver`,
  `WeatherProvider`, `DeviceFactory`, repositorio de configuración, `clock`, `wait`,
  `http_get`).
- El paquete MUST importarse y ejecutarse completo en una máquina de desarrollo sin
  Raspberry Pi: las dependencias de hardware se cargan de forma perezosa dentro del
  driver que las necesita.
- El driver GPIO MUST verificar la plataforma antes de tocar el hardware y fallar con
  un error de dominio (`GpioDriverError`), no con una excepción de librería.

**Rationale:** la lógica de negocio se valida en segundos en cualquier portátil, y el
hardware se sustituye sin reescribir el núcleo.

### III. Configuración validada y explícita

La configuración es contrato, no sugerencia. Esta exigencia es **independiente del
origen**: base de datos local o remota, fichero, API HTTP o cualquier interfaz futura.

- La configuración MUST validarse íntegramente al cargar, con un error de dominio y un
  mensaje accionable que identifique el campo ofensor y, cuando corresponda, la entidad a
  la que pertenece.
- El rechazo MUST ser completo: NUNCA se aplica una configuración parcialmente válida.
- NO se permiten valores por defecto implícitos que alteren comportamiento físico
  (pines, potencia máxima, ventanas de carga): si son necesarios, se declaran y
  documentan.
- La localización del almacén de configuración y sus credenciales —cadena de conexión,
  secretos como la API key de AEMET— MUST proceder de variables de entorno o del mecanismo
  protegido del despliegue. NUNCA del propio almacén de configuración, del repositorio ni
  de los logs.
- El esquema del almacén de configuración MUST estar versionado. Las migraciones MUST
  aplicarse en orden conservando los datos existentes. Un esquema de versión **posterior**
  a la que el servicio comprende MUST rechazar el arranque, en lugar de operar sobre datos
  que no entiende (ver Principio I).
- El estado persistido MUST ser versionado y su carga tolerante: un registro corrupto o
  de versión desconocida se descarta con log de error y se trata como "sin plan"
  (ver Principio I).

**Rationale:** un pin mal interpretado o una potencia por defecto silenciosa se paga en
el cuadro eléctrico, y da igual si el valor venía de un fichero, de una tabla o de un
formulario web.

### IV. Continuidad y degradación observable

El servicio está pensado para correr sin supervisión durante meses.

- Un fallo de refresco de plan MUST conservar el plan persistido y reintentar con la
  cadencia configurada; nunca terminar el proceso.
- La pérdida de acceso al almacén de configuración con el servicio ya en marcha MUST
  conservar el plan en ejecución y reintentar con la cadencia configurada; MUST NOT
  terminar el proceso ni dejar salidas en estado indeterminado.
- El plan activo MUST persistirse de forma atómica y durable, de modo que un corte de
  corriente no deje estado a medias.
- La degradación (proveedor secundario, almacén inaccesible, reintento, ausencia de plan)
  MUST registrarse en la transición —al entrar y al salir— y MUST NOT registrarse en cada
  iteración del bucle de control.
- Toda transición de estado de una salida MUST quedar registrada con id, valor e instante.
- Un fallo al escribir un registro de auditoría o de histórico MUST registrarse como error
  y MUST NOT interrumpir la planificación, la conmutación de salidas ni el proceso: la
  observabilidad nunca puede ser causa de una parada.

**Rationale:** sin observabilidad de las transiciones no hay forma de auditar por qué un
acumulador cargó o no una noche concreta; y un fallo del registro de auditoría no puede
convertirse en un fallo del control.

### V. Tests deterministas sin hardware

- Toda feature o corrección MUST entrar con tests en `tests/`, en el módulo espejo del
  código tocado.
- Los tests MUST ser deterministas: se inyectan dobles (device factory falsa, `http_get`
  falso, repositorio de configuración falso, reloj y `wait` controlados). PROHIBIDO un test
  que requiera Raspberry Pi, red real, base de datos remota, o que duerma en tiempo real.
- La suite completa (`pytest`) MUST pasar antes de considerar una tarea terminada.
- Los caminos de fallo del Principio I (error de driver, plan ausente, id desconocido,
  apagado parcialmente fallido, almacén de configuración inaccesible o inválido) MUST tener
  cobertura explícita.

**Rationale:** el comportamiento crítico es precisamente el de los caminos de error, y
esos no se prueban a mano en una Pi.

### VI. Simplicidad y stdlib primero

- Las dependencias de runtime se mantienen al mínimo. Añadir una dependencia MUST
  justificarse en el `plan.md` de la feature.
- Lo que solo hace falta en el despliegue real o en un borde concreto —hardware
  (`gpiozero`, `lgpio`), persistencia, API HTTP, interfaz web— MUST vivir en un extra
  opcional siempre que sea posible, no en el runtime base.
- El planificador y el modelo térmico MUST poder importarse y ejecutarse sin ninguna de
  esas dependencias de borde instalada.
- Se usan `dataclass(frozen=True)`, `Protocol` y type hints completos; se prefiere la
  estructura de datos inmutable al objeto mutable con estado escondido.
- YAGNI: no se añaden capas de abstracción para necesidades hipotéticas.

**Rationale:** el objetivo de despliegue es una Raspberry Pi 2B; cada dependencia es
peso, superficie de fallo y una actualización que puede romper el arranque. Confinarlas en
extras mantiene el núcleo verificable en cualquier máquina.

## Restricciones de plataforma

- Python 3.12 o superior. Objetivo de despliegue: Raspberry Pi 2B (ARMv7 de 32 bits,
  ~1 GB de RAM) con systemd (`deploy/`). El consumo de CPU y memoria del bucle de control
  debe ser despreciable frente a esa máquina.
- **Origen de la configuración:** base de datos, con dos modos soportados y comportamiento
  idéntico entre ambos: SQLite local en el propio dispositivo, o PostgreSQL remoto.
  PostgreSQL es **siempre** externo al dispositivo de despliegue; instalar un motor de base
  de datos en la Raspberry Pi 2B queda descartado por recursos.
- **Dependencias declaradas de persistencia:** SQLAlchemy y Alembic. Se aceptan como
  excepción justificada al Principio VI: dan un único código para ambos motores y
  migraciones versionadas que conservan datos, frente a la alternativa de mantener y probar
  a mano dos dialectos de SQL. Viven en un extra opcional según el Principio VI.
- **Artefactos de frontend:** MUST compilarse fuera del dispositivo de despliegue y
  desplegarse ya construidos. NUNCA se ejecuta una cadena de construcción de Node en la Pi.
- **Interfaces de usuario:** la CLI (`dynamic-thermal-charge`) deja de ser la única. Se
  prevén API HTTP, interfaz web e integración domótica. Cada una MUST ser un borde según el
  Principio II, y ninguna MUST activar una salida sin pasar por el controlador fail-safe
  del Principio I. Añadir una interfaz nueva NO requiere enmendar esta constitución.
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

**Version**: 1.1.0 | **Ratified**: 2026-08-26 | **Last Amended**: 2026-08-26
