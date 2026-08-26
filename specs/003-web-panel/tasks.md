---

description: "Task list for 003-web-panel"
---

# Tasks: Panel web de estado, configuración e histórico

**Input**: Design documents from `/specs/003-web-panel/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`. Las features
`001-config-database` y `002-config-api` deben estar implementadas: el panel consume la API.

**Tests**: OBLIGATORIOS. El Principio V exige cobertura de la lógica delicada, que aquí es la
interpretación del estado sin confirmar: donde un error miente al operador.

**Organization**: agrupadas por historia de usuario.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable — toca ficheros distintos y no depende de tareas incompletas
- **[Story]**: historia de usuario de `spec.md` (US1…US6)

## Path Conventions

El panel vive en `frontend/`, con su propia cadena de herramientas.
`src/dynamic_thermal_charge/` **no cambia en una sola línea**. Los artefactos de despliegue van en
`deploy/nginx/` y `scripts/`.

## Orden de las historias P1 y por qué

`spec.md` marca como P1 las historias 1, 2, 3, 4 y 6. El orden de implementación **no** es su
numeración:

- **US4 (acceso) va primera.** Sin credencial no funciona ninguna otra vista, y añadir el
  interceptor después obliga a rehacer cada llamada y cada test.
- **US2 (no mentir) va antes de US1 (ver el estado).** El tipo de tres valores y su presentación
  deciden **qué se puede pintar** en la vista de estado. Construir la vista primero significaría
  decidir después si lo que ya muestra es cierto, que es como se pierde la distinción.
- **US6 (desplegar) va al final**, cuando hay algo que desplegar.

El orden es **US4 → US2 → US1 → US3 → US5 → US6**.

---

## Phase 1: Setup

- [X] T001 Generar el espacio de trabajo con `ng new frontend --standalone --zoneless --test-runner vitest --style css --routing --ssr false --ai-config none --skip-git --skip-install=false` desde la raíz del repositorio, de modo que quede `frontend/package.json` y **no** `frontend/panel/package.json`. Renombrar el proyecto interno a `panel` en `frontend/angular.json` si el generador lo nombra a partir del directorio
- [X] T002 Verificar que `frontend/node_modules/zone.js` **no** existe: `--zoneless` debe retirarlo de verdad, y es la mitad del ahorro de runtime (research D1)
- [X] T003 [P] Añadir `frontend/node_modules/` y `frontend/dist/` a `.gitignore`
- [X] T004 Declarar en `frontend/angular.json` el presupuesto de paquete inicial: **500 kB en bruto** y **150 kB transferidos**, de modo que la compilación **falle** al superarlo. Es lo que impide que una dependencia añadida «solo para probar» se cuele (research D4)
- [X] T005 [P] Configurar en `frontend/angular.json` el intermediario de desarrollo hacia `http://127.0.0.1:8420`, para que en desarrollo tampoco hagan falta orígenes cruzados
- [X] T006 [P] Añadir a `frontend/package.json` los guiones `start`, `build` y `test`, y documentar en su cabecera que **nunca** se ejecutan en la Raspberry Pi
- [X] T007 Comprobar que `npm test` y `npm run build` funcionan sobre el andamiaje recién generado, antes de escribir código propio

---

## Phase 2: Foundational (prerrequisitos bloqueantes)

**Purpose**: los tipos de la API, el tipo de tres valores y el sondeo. Al terminar no hay ninguna
vista, y por tanto nada que mienta todavía.

### Tipos derivados del contrato de la fase 2

- [X] T008 Escribir `frontend/src/app/core/api.types.ts` con los tipos de las respuestas de la API, derivados de `specs/002-config-api/contracts/http-api.md`. `output_on` MUST tiparse como `boolean | null`, no como `boolean`
- [X] T009 Añadir a `api.types.ts` los tipos de configuración, histórico y error, con el código de error como unión de literales, no como cadena libre

### El tipo de tres valores: el corazón de la fase

- [X] T010 Implementar en `frontend/src/app/core/output-state.ts` el tipo `OutputState` de **tres** variantes —`on`, `off`, `unknown` con su último valor conocido y su instante— según `data-model.md`. NO un booleano: un booleano colapsaría `null` en `false` en la primera conversión y la información se perdería sin que nada avisara
- [X] T011 Implementar en `output-state.ts` la derivación desde la respuesta de la API: `output_on` nulo produce `unknown`, y la variante lleva `last_known_output_on` y `changed_at`
- [X] T012 Escribir `frontend/src/app/core/output-state.spec.ts` con la tabla completa: `true` con vigencia, `false` con vigencia, `null` sin vigencia, y `null` con último valor conocido tanto encendido como apagado
- [X] T013 Añadir a `output-state.spec.ts` la comprobación de que **ninguna** entrada produce `on` u `off` cuando el estado no es vigente. Es la aserción que impide que la distinción se pierda

### Antigüedades a partir de los datos de la API

- [X] T014 Implementar en `frontend/src/app/shared/age/age.ts` el formateo de antigüedad **a partir del `age_seconds` y los instantes que da la API**, nunca de una diferencia contra el reloj del navegador (research D9)
- [X] T015 Escribir `frontend/src/app/shared/age/age.spec.ts` incluyendo el caso del reloj desfasado: con el reloj del navegador adelantado o atrasado horas respecto al dispositivo, la antigüedad mostrada MUST seguir siendo la que da la API

### Sondeo con parada en segundo plano

- [X] T016 Implementar en `frontend/src/app/core/poll.ts` el sondeo periódico basado en señales, con la cadencia de `data-model.md` —5 s por defecto, ajustable entre 2 y 60—, que **se detiene** cuando el documento no está visible y se reanuda **de inmediato** al volver al frente, no en el siguiente tick (FR-046)
- [X] T017 Escribir `frontend/src/app/core/poll.spec.ts` con reloj controlado: emite a la cadencia por defecto, acota una cadencia fuera de rango a los límites, se detiene al ocultarse, y refresca inmediatamente al volver a hacerse visible

### Traducción de errores

- [X] T018 Escribir `frontend/src/app/core/no-local-clock.spec.ts`: guardia que recorra las fuentes de `frontend/src/app/` y falle si alguna usa `Date.now()` o `new Date()` para calcular antigüedades, salvo en `age.ts`, que las recibe ya calculadas de la API. Sin esta guardia, un componente futuro reintroduciría el reloj local y nada fallaría (FR-016)
- [X] T019 Implementar en `frontend/src/app/core/errors.ts` la traducción de cada código de error de la API a una explicación accionable, según la tabla de `data-model.md`
- [X] T020 Redactar con especial cuidado en `errors.ts` los dos casos de esquema: el panel **no puede** arreglarlo, así que el mensaje MUST decir qué ejecutar **en el dispositivo** y que el panel no puede hacerlo, para que nadie busque un botón que no existe (FR-032)
- [X] T021 Escribir `frontend/src/app/core/errors.spec.ts` comprobando que **todos** los códigos del contrato de la fase 2 tienen traducción, y que ninguna traducción contiene jerga técnica ni trazas

---

## Phase 3: US4 — Entrar y salir del panel (P1)

**Goal**: nada se muestra sin credencial, y la credencial no queda en el equipo.

**Independent Test**: recorrer el ciclo sin credencial, con una incorrecta, con la correcta,
recargando y cerrando sesión, comprobando qué se muestra y qué se almacena.

**Por qué va primera**: sin credencial no funciona ninguna otra vista, y añadir el interceptor
después obliga a rehacer cada llamada y cada test.

- [X] T022 [US4] Implementar `frontend/src/app/core/auth.ts` con la sesión sobre `sessionStorage`: sobrevive a recargar y desaparece al cerrar la pestaña (FR-002)
- [X] T023 [US4] Implementar `frontend/src/app/core/auth.interceptor.ts` que añada la credencial a cada llamada a la API en la cabecera, **nunca** en la dirección ni en parámetros de consulta (FR-003)
- [X] T024 [US4] Hacer en `frontend/src/app/core/auth.interceptor.ts` que el interceptor cierre la sesión y vuelva a la pantalla de acceso ante un rechazo de credencial, con la explicación de que hay que introducirla de nuevo, sin error técnico (FR-006)
- [X] T025 [US4] Implementar la pantalla de acceso en `frontend/src/app/core/login/` y el guardián de rutas que impida mostrar cualquier dato de la instalación sin credencial (FR-001)
- [X] T026 [US4] Implementar en `frontend/src/app/core/auth.ts` y en la barra de la aplicación el cierre de sesión explícito que borre la credencial del navegador (FR-005)
- [X] T027 [US4] Escribir `frontend/src/app/core/auth.spec.ts`: la credencial sobrevive a recargar, no persiste en `localStorage`, y se borra al cerrar sesión
- [X] T028 [US4] Escribir `frontend/src/app/core/auth.interceptor.spec.ts` con el arnés HTTP en memoria: la cabecera se añade, la dirección **no** contiene la credencial, y un 401 cierra la sesión
- [X] T029 [US4] Añadir a `auth.spec.ts` la comprobación de que una credencial incorrecta se reporta como no válida **sin** dar pistas sobre en qué se diferencia de la correcta (FR-004)
- [X] T030 [US4] Añadir a `frontend/src/app/core/auth.interceptor.spec.ts` el caso de credencial rotada en el servidor **durante el uso** (FR-006): una llamada cualquiera devuelve 401, y el panel vuelve a la pantalla de acceso con la explicación de que hay que introducirla de nuevo, **sin** mostrar un error técnico ni dejar la vista a medias
- [X] T031 [US4] Añadir a `frontend/src/app/core/auth.spec.ts` la comprobación de que la credencial no aparece en ningún almacenamiento persistente del navegador tras un ciclo completo de uso (FR-003, SC-007)

**Checkpoint**: el panel está protegido antes de tener nada que proteger.

---

## Phase 4: US2 — No dejar que el panel mienta (P1)

**Goal**: la distinción entre estado confirmado y sin confirmar sobrevive hasta el píxel.

**Independent Test**: presentar al panel cada una de las cuatro situaciones del controlador y
comprobar qué se muestra y qué no se afirma.

**Por qué va antes de la vista de estado**: el tipo y su presentación deciden qué se puede pintar.
Construir la vista primero significaría decidir después si lo que ya muestra es cierto.

- [X] T032 [US2] Implementar `frontend/src/app/shared/output-indicator/` con **tres** apariencias distinguibles: encendido confirmado, apagado confirmado y sin confirmar. La tercera MUST llevar el último valor conocido etiquetado como pasado, con su instante (FR-011)
- [X] T033 [US2] Hacer en `frontend/src/app/shared/output-indicator/` que las tres apariencias se distingan **sin depender del color**: forma o texto además del color. Un panel que informa sobre una instalación eléctrica no puede excluir a quien no distingue verde de gris (FR-036)
- [X] T034 [US2] Implementar en `frontend/src/app/status/controller-health/` la presentación de las cuatro situaciones del controlador, con la orientación de qué comprobar en cada caso anómalo, según la tabla de `contracts/panel.md` (FR-012)
- [X] T035 [US2] Implementar en `frontend/src/app/status/controller-health/` el aviso visible de estado no vigente, indicando **desde cuándo** no se ve al controlador (FR-009)
- [X] T036 [US2] Implementar en `frontend/src/app/status/controller-health/` la advertencia **prominente** de sospecha de más de un controlador, explicando el riesgo eléctrico. Prominente, no una nota discreta (FR-013)
- [X] T037 [US2] Escribir `frontend/src/app/shared/output-indicator/output-indicator.spec.ts`: las tres variantes producen salidas distinguibles, y la de sin confirmar incluye la etiqueta de pasado y el instante
- [X] T038 [US2] Añadir a `output-indicator.spec.ts` la comprobación de que la distinción **no** depende solo del color: la salida accesible difiere entre las tres variantes
- [X] T039 [US2] Escribir `frontend/src/app/status/controller-health/controller-health.spec.ts` con las cuatro situaciones, comprobando que `never_seen` y `stale` se distinguen y que cada anómala orienta
- [X] T040 [US2] Añadir a `frontend/src/app/status/controller-health/controller-health.spec.ts` la comprobación de que la advertencia de más de un controlador aparece solo cuando la API la señala, y con el texto del riesgo

**Checkpoint**: existe el mecanismo que impide mentir, probado, antes de haber pintado nada.

---

## Phase 5: US1 — Ver de un vistazo qué está pasando (P1)

**Goal**: el estado completo en una pantalla, honesto sobre su vigencia.

**Independent Test**: contra una API con estado conocido, cada dato mostrado coincide con lo que
la API devuelve.

- [X] T041 [US1] Implementar `frontend/src/app/core/api.ts` como el único módulo que conoce las direcciones de la API, con los métodos de estado, configuración e histórico
- [X] T042 [US1] Implementar la vista de estado en `frontend/src/app/status/status.ts` y su plantilla: acumuladores, potencia, plan, previsión y reparto
- [X] T043 [US1] Hacer en `frontend/src/app/status/status.ts` y su plantilla que la potencia instantánea **no se muestre** cuando el estado no es vigente. Ni una cifra, ni un cero: un cero afirma que no se consume nada (FR-010)
- [X] T044 [US1] Mostrar en `frontend/src/app/status/` los minutos no atendidos de forma **destacada** cuando existan, no enterrados en una tabla (FR-015)
- [X] T045 [US1] Indicar en `frontend/src/app/status/` explícitamente la ausencia de plan en curso, en lugar de una vista vacía o valores a cero (FR-014)
- [X] T046 [US1] Conectar el sondeo de T016 a `frontend/src/app/status/status.ts`, sin perder la posición de lectura ni el foco al refrescar (FR-008)
- [X] T047 [US1] Implementar en `frontend/src/app/status/status.ts` el comportamiento ante una API que no responde (FR-030): se indica, **se conserva lo último mostrado marcado como no actual**, y no se vacía la pantalla ni se queda cargando indefinidamente. Vaciar destruye información útil; dejarla igual miente
- [X] T048 [US1] Añadir a `frontend/src/app/status/status.spec.ts` el caso de API sin respuesta: los datos anteriores siguen visibles, marcados como no actuales, y aparece el aviso de que no se pudo contactar
- [X] T049 [US1] Hacer en `frontend/src/app/status/status.css` y `frontend/src/styles.css` la vista utilizable en pantalla de teléfono, sin desplazamiento horizontal de la página (FR-034)
- [X] T050 [US1] Escribir `frontend/src/app/status/status.spec.ts` con el arnés HTTP en memoria: el caso vigente muestra potencia, plan, previsión con su origen y reparto
- [X] T051 [US1] Añadir a `status.spec.ts` los dos casos no vigentes —silencioso y nunca visto— comprobando que **no** se muestra potencia y que **ninguna** salida aparece como cargando
- [X] T052 [US1] Añadir a `frontend/src/app/status/status.spec.ts` el caso degradado, comprobando que se avisa **sin** ocultar que el estado sí es actual
- [X] T053 [US1] Añadir a `frontend/src/app/status/status.spec.ts` los casos de instalación sin plan, sin acumuladores, y con previsión de reserva distinguida de la del proveedor real

**Checkpoint**: el panel muestra el estado y es el MVP de la fase.

---

## Phase 6: US3 — Cambiar la configuración sin abrir una consola (P1)

**Goal**: editar desde el navegador con los mismos rechazos y las mismas garantías que la API.

**Independent Test**: aplicar cambios válidos e inválidos y comprobar qué queda, qué se rechaza y
cómo se presenta cada rechazo.

- [X] T054 [US3] Implementar la vista de configuración en `frontend/src/app/config/config.ts`, con la revisión leída y los valores editables de instalación, proveedor meteorológico y acumuladores
- [X] T055 [US3] Enviar desde `frontend/src/app/config/config.ts` en cada escritura la revisión leída, y ante conflicto avisar de que la configuración cambió y ofrecer releer, **sin** sobrescribir ni reintentar solo (FR-019)
- [X] T056 [US3] Mostrar en `frontend/src/app/config/` cada rechazo de la API **junto al campo** que lo causó cuando la API identifique un campo, conservando visible el valor anterior (FR-018)
- [X] T057 [US3] Implementar `frontend/src/app/shared/confirm/` y exigir confirmación explícita, que diga qué se va a cambiar, **solo** para `max_total_power_kw`, `pin` y `active_high`. Los demás campos sin ceremonia: pedir confirmación para todo enseña a confirmar sin leer (FR-020)
- [X] T058 [US3] Implementar en `frontend/src/app/config/heaters/` el alta y la baja de acumuladores, exigiendo confirmación en la baja y avisando de que su histórico se conserva (FR-021)
- [X] T059 [US3] Advertir desde `frontend/src/app/config/config.ts` antes de descartar un formulario con cambios sin guardar (FR-022)
- [X] T060 [US3] Conservar en `frontend/src/app/config/config.ts` lo introducido en el formulario cuando una escritura falle por pérdida de conectividad (FR-033)
- [X] T061 [US3] Validar en `frontend/src/app/config/config.ts` en el cliente **solo** para dar respuesta inmediata, sin reimplementar ni relajar ninguna regla: la API sigue siendo la autoridad (FR-023)
- [X] T062 [US3] Escribir `frontend/src/app/config/config.spec.ts`: edición correcta de un campo de instalación y de un campo de acumulador, con la revisión enviada
- [X] T063 [US3] Añadir a `config.spec.ts` el caso de conflicto: se avisa, se ofrece releer, y **no** se reintenta automáticamente
- [X] T064 [US3] Añadir a `frontend/src/app/config/config.spec.ts` los casos de rechazo por campo, comprobando que el mensaje queda asociado al campo y que el valor anterior sigue visible
- [X] T065 [US3] Añadir a `frontend/src/app/config/config.spec.ts` el caso de valor con aspecto de credencial, comprobando que se muestra el motivo y la indicación de que los secretos van por variable de entorno
- [X] T066 [US3] Añadir a `frontend/src/app/config/config.spec.ts` la comprobación de que los tres campos eléctricos exigen confirmación y que el resto **no** la exige
- [X] T067 [US3] Añadir a `frontend/src/app/config/config.spec.ts` el caso de fallo de red a mitad de una edición, comprobando que se informa y que el formulario conserva lo introducido

**Checkpoint**: la instalación se configura por completo desde el navegador.

---

## Phase 7: US5 — Auditar el pasado desde el navegador (P2)

**Goal**: reconstruir cualquier noche del periodo retenido sin acceder al dispositivo.

**Independent Test**: con un histórico conocido, recorrer las tablas, filtrar y paginar.

- [X] T068 [US5] Implementar las vistas de histórico en `frontend/src/app/history/` para planes, previsiones y transiciones, en tablas con los más recientes primero (FR-024)
- [X] T069 [US5] Implementar en `frontend/src/app/history/` el filtro por rango de fechas y, en transiciones, por acumulador (FR-025)
- [X] T070 [US5] Implementar en `frontend/src/app/history/` la navegación entre páginas usando el cursor de la API, tratándolo como **opaco**: se reenvía tal cual, sin interpretarlo ni construirlo (FR-026)
- [X] T071 [US5] Presentar en `frontend/src/app/history/` un rango sin datos como vacío, **no** como error, y avisar de un rango invertido antes de consultar (FR-027)
- [X] T072 [US5] Indicar en `frontend/src/app/history/` los acumuladores que ya no están en la configuración, sin ocultarlos (FR-028)
- [X] T073 [US5] Distinguir en `frontend/src/app/history/` el origen de cada previsión, en particular si vino del valor de reserva (FR-029)
- [X] T074 [US5] Hacer en `frontend/src/app/history/history.css` que las tablas anchas se puedan recorrer sin romper la disposición de la página (FR-035), con el contenedor de desplazamiento horizontal acotado a la tabla y no al documento. Se verifica por revisión visual: una comprobación automatizada de disposición exigiría un navegador real, que está fuera de alcance
- [X] T075 [US5] Escribir `frontend/src/app/history/history.spec.ts`: orden, paginación por cursor sin repetir ni omitir, filtros y rango vacío
- [X] T076 [US5] Añadir a `frontend/src/app/history/history.spec.ts` el caso de rango invertido y el de acumulador ausente de la configuración pero presente en el histórico

---

## Phase 8: US6 — Instalarlo y servirlo en la Raspberry Pi (P1)

**Goal**: el panel llega al dispositivo copiando ficheros, y la API sigue sin exponerse.

**Independent Test**: seguir el procedimiento documentado sobre una instalación limpia y comprobar
que el panel carga y opera.

- [X] T077 [US6] Escribir `deploy/nginx/dynamic-thermal-charge.conf` según `contracts/nginx.md`: raíz del panel, intermediario hacia `127.0.0.1:8420`, y la comprobación de salud
- [X] T078 [US6] Añadir en la configuración `try_files $uri $uri/ /index.html`. Sin esto, recargar una dirección interna del panel devuelve 404 porque en el disco no existe ese fichero (FR-040)
- [X] T079 [US6] Añadir la caché diferenciada: recursos con huella en el nombre como inmutables y con caducidad larga, e `index.html` con `no-cache`. Cachear `index.html` es exactamente el fallo que hace que el operador actualice, recargue y siga viendo la interfaz antigua (FR-041)
- [X] T080 [US6] Declarar en `deploy/nginx/dynamic-thermal-charge.conf` explícitamente la propagación de la cabecera de autorización, para que un cambio futuro no la rompa en silencio y deje todo devolviendo 401
- [X] T081 [US6] Añadir a `deploy/nginx/dynamic-thermal-charge.conf` el bloque de cifrado en tránsito **comentado**, con la advertencia de qué se asume sin él. Es la vía que la fase anterior dejó como riesgo documentado (FR-042)
- [X] T082 [US6] Añadir la opción `--with-panel` a `scripts/install-service.sh`: deja la configuración del sitio disponible, avisa de que hay que copiar el `dist/` compilado fuera, y **no** arranca ni habilita nginx ni instala Node (FR-037, FR-043)
- [X] T083 [US6] Ampliar `tests/test_deployment.py` para verificar los invariantes del sitio de nginx: `try_files` presente, `index.html` sin cachear, `proxy_pass` a `127.0.0.1`, cabecera de autorización propagada, y bloque de cifrado presente y comentado
- [X] T084 [US6] Añadir a `tests/test_deployment.py` la guardia de despliegue: el instalador **no** menciona `npm`, `node`, `nodejs`, `yarn` ni `pnpm` como algo a instalar en el dispositivo; **no** arranca ni habilita nginx; y `.gitignore` excluye `frontend/node_modules` y `frontend/dist`, de modo que 253 MB de dependencias y el artefacto compilado no puedan entrar en el repositorio (FR-037, SC-010)
- [X] T085 [US6] Añadir a `tests/test_deployment.py` la comprobación de que la configuración de nginx **no** sirve `/var/lib` ni ningún fichero de la base de datos

---

## Phase 9: Documentación y cierre

- [X] T086 Añadir a `README.md` la sección del panel: requisitos de Node en la máquina de construcción, desarrollo local, compilación y despliegue por copia
- [X] T087 Añadir a `README.md` el aviso explícito de que **el panel se compila fuera del dispositivo** y de que en la Raspberry Pi no se instala Node: un `npm install` en un Cortex-A7 con 1 GB no termina
- [X] T088 Añadir a `README.md` cómo añadir cifrado en tránsito y qué riesgo se asume sin él: sirve en claro, la credencial viaja legible, y quien la tenga puede cambiar la potencia máxima y los pines (FR-042)
- [X] T089 Añadir a `README.md` la comprobación de que la API no está expuesta tras el despliegue, con los comandos concretos
- [X] T090 [P] Añadir a `README.md` la tabla de diagnóstico del panel de `quickstart.md`
- [X] T091 Comprobar con `git diff --stat 002-config-api -- src/ pyproject.toml` que **ni una línea** de `src/dynamic_thermal_charge/` ni de `pyproject.toml` ha cambiado en esta fase, y que la suite de Python pasa sin modificaciones (FR-047). Es la afirmación fuerte del plan: el panel es completamente externo
- [X] T092 Comprobar que `npm test` pasa sin red, sin la API real y sin navegador, y que `npm run build` respeta el presupuesto de paquete
- [X] T093 Anotar en `research.md` D4 el tamaño real del paquete del panel terminado, frente al presupuesto declarado
- [ ] T094 **MANUAL, requiere hardware — diferida, fuera del criterio de fase completa.** Desplegar en la Raspberry Pi y comprobar sobre el dispositivo: que el panel carga desde otro equipo de la red, que recargar una ruta interna funciona, que tras actualizar se recoge la versión nueva sin borrar caché, y que la API sigue escuchando solo en `127.0.0.1`

---

## Dependencies

```text
Phase 1 Setup
     ↓
Phase 2 Foundational   ← tipos, el tipo de tres valores, antigüedades, sondeo, errores
     ↓
Phase 3 US4 (acceso)   ← antes de que exista cualquier vista que proteger
     ↓
Phase 4 US2 (no mentir)   ← decide qué puede pintar la vista de estado
     ↓
Phase 5 US1 (estado)   ← MVP de la fase
     ↓
Phase 6 US3 (configuración)
     ↓
Phase 7 US5 (histórico)
     ↓
Phase 8 US6 (despliegue)   ← cuando ya hay algo que desplegar
     ↓
Phase 9 Documentación y cierre
```

Dependencias que conviene no perder de vista:

- **T010 a T013 antes de T032.** El componente que pinta tres estados no puede escribirse antes de
  que exista el tipo de tres estados, o se escribirá contra un booleano y habrá que rehacerlo.
- **T032 y T033 antes de T042.** La vista de estado usa el indicador; si se escribe antes, usará
  un booleano y la distinción se perderá exactamente donde importa.
- **T022 a T024 antes de cualquier vista.** El interceptor se aplica a todas las llamadas; si las
  vistas llegan antes, existen sin protección y sus tests hay que rehacerlos.
- **T004 desde el principio.** El presupuesto de paquete solo sirve si está declarado antes de
  empezar a añadir código; puesto al final, se ajustaría a lo que haya en lugar de acotarlo.
- **T014 y T015 antes de T034.** La presentación de la salud del controlador muestra antigüedades,
  y calcularlas contra el reloj local es el error que T015 impide.
- **T016 antes de T046.** No se puede conectar a la vista un sondeo que no existe.
- **T077 a T081 antes de T083.** Los invariantes se verifican sobre una configuración escrita.

## Parallel Execution Examples

Dentro de la fase 1: T003, T005 y T006 en paralelo.

Dentro de la fase 2: el bloque del tipo de tres valores (T010–T013) es paralelo al de antigüedades
(T014–T015), al de sondeo (T016–T017) y al de errores (T019–T021): ficheros distintos, siempre que
T008 y T009 estén hechos.

Dentro de la fase 8: T082 (instalador) es paralelo a T077–T081 (configuración de nginx).

Dentro de la fase 9: T090 en paralelo con el resto.

No paralelizar dentro de un mismo fichero: T010 y T011 tocan `output-state.ts`; T077 a T081 tocan
la configuración de nginx; T083 a T085 tocan `tests/test_deployment.py`; casi toda la fase 6 toca
`config.ts`.

## Implementation Strategy

**MVP mínimo utilizable**: fases 1 a 5. Al terminarlas hay un panel que pide credencial y muestra
el estado con honestidad sobre su vigencia. Es lo que se consulta a diario.

**Primer punto de despliegue razonable**: añadir las fases 6 y 8. Sin la 6 el panel es un visor y
seguiría haciendo falta la consola para operar; sin la 8 no llega al dispositivo.

**Completar la fase**: fases 7 y 9. La 9 es obligatoria antes de desplegar: sin T087 y T088 el
operador no sabe que no debe compilar en la Pi ni qué riesgo asume sin cifrado.

**Fase posterior del proyecto** (fuera de este `tasks.md`): integración con Home Assistant.

## Resumen

| Fase | Historia | Tareas | Prioridad |
| --- | --- | ---: | --- |
| 1 Setup | — | 7 (T001–T007) | — |
| 2 Foundational | — | 14 (T008–T021) | bloqueante |
| 3 | US4 acceso | 10 (T022–T031) | P1 |
| 4 | US2 no mentir | 9 (T032–T040) | P1 |
| 5 | US1 estado | 13 (T041–T053) | P1 |
| 6 | US3 configuración | 14 (T054–T067) | P1 |
| 7 | US5 histórico | 9 (T068–T076) | P2 |
| 8 | US6 despliegue | 9 (T077–T085) | P1 |
| 9 Documentación y cierre | — | 9 (T086–T094) | — |
| **Total** | | **94** | |

De las 94, **93 son ejecutables en máquina de desarrollo**. T094 requiere la Raspberry Pi, está
marcada como manual y queda fuera del criterio de fase completa.

Cobertura: los 47 requisitos funcionales y los 13 criterios de éxito de `spec.md` tienen al menos
una tarea asociada, tras cerrar en la revisión de `/speckit-analyze` los huecos de FR-006, FR-016,
FR-030, FR-037, FR-047 y SC-010.

## Revisión de `/speckit-analyze`

Las cuatro tareas siguientes se añadieron al cerrar los hallazgos del análisis:

| Tarea | Hallazgo | Qué cerraba |
| --- | --- | --- |
| T020 | F5 | Nada impedía que un componente futuro reintrodujese el reloj local para calcular antigüedades |
| T031 | F2 (HIGH) | El caso de credencial rotada **durante** el uso no se probaba |
| T045, T046 | F1 (HIGH) | FR-030 —conservar lo último mostrado con la API caída— no tenía ninguna tarea |

Los demás se cerraron corrigiendo artefactos: **F3** (`/docs` y `/openapi.json` se retiran del
sitio de nginx: el panel no los usa y publicarlos amplía la superficie sin necesidad), **F4** (la
cadencia de sondeo queda fijada en 5 s por defecto, acotada entre 2 y 60, coincidiendo con el
sondeo del controlador), **F6** (T084 pasa a guardia real: el instalador no menciona gestores de
Node, y `.gitignore` excluye los 253 MB de dependencias y el artefacto compilado), **F7** (`ng new
panel` habría producido `frontend/panel/`, no `frontend/`), **F8** (T091 comprueba con `git diff`
que **ni una línea** de `src/` cambió, que es la afirmación fuerte del plan), **F9** y **F10**.

La honestidad del panel —lo que impide que mienta— está cubierta por T010–T013, T032–T033,
T037–T038, T043, T051 y T015.
