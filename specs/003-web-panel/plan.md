# Implementation Plan: Panel web de estado, configuración e histórico

**Branch**: `003-web-panel` | **Date**: 2026-08-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-web-panel/spec.md`

**Constitución aplicada**: 1.1.0 · **Depende de**: `001-config-database`, `002-config-api`

## Summary

Un panel web que muestra el estado de la instalación, permite editar su configuración y consultar
el histórico, consumiendo exclusivamente la API de la fase anterior. Se compila fuera del
dispositivo y nginx lo sirve en la Raspberry Pi, haciendo además de intermediario hacia la API.

El problema central no es pintar datos: es **no mentir al pintarlos**. La fase anterior se tomó el
trabajo de distinguir «esto está pasando ahora» de «esto es lo último que se supo», y el panel es
el último metro donde esa distinción se puede perder — precisamente donde el operador decide. La
respuesta técnica es un tipo de **tres** valores para el estado de una salida, de modo que el
comprobador de tipos obligue a decidir qué se pinta cuando no hay prueba.

Enfoque técnico: **Angular 22 con componentes autónomos, señales y sin `zone.js`**, probado con
**Vitest**, sin librería de componentes. La credencial vive en `sessionStorage` y la añade un
interceptor. nginx sirve el `dist/` y hace de proxy a `127.0.0.1:8080`, con lo que el navegador ve
un solo origen y **la API nunca se expone en la red**.

Nada de `src/dynamic_thermal_charge/` cambia. FR-045 de la fase anterior —la API no sirve ficheros
estáticos— sigue siendo cierto, porque los sirve nginx.

Detalle y mediciones en [research.md](./research.md); modelo de vista en
[data-model.md](./data-model.md); contratos en [contracts/](./contracts/).

## Technical Context

**Language/Version**: TypeScript sobre Angular 22.1. Node **≥ 22.22.3 / ≥ 24.15 / ≥ 26** en la
máquina de construcción, **ninguno** en el dispositivo. El proyecto de Python no cambia.

**Primary Dependencies**:

| Dependencia | Ámbito | Justificación (Principio VI) |
| --- | --- | --- |
| `@angular/*` 22 | `frontend/` runtime | El marco. Componentes autónomos y señales son ya el valor por defecto |
| `rxjs`, `tslib` | `frontend/` runtime | Transitivas del marco |
| `vitest`, `jsdom` | `frontend/` desarrollo | Ejecutor **por defecto** de Angular 22; corre sin navegador |
| `@angular/build`, `cli`, `compiler-cli`, `typescript`, `prettier` | `frontend/` desarrollo | Cadena de construcción |
| `zone.js` | **ausente** | `--zoneless`: verificado que no queda instalado |
| Angular Material u otra librería de componentes | **descartada** | Tres vistas no justifican su peso; el requisito de accesibilidad que importa (no depender del color) hay que resolverlo a mano de todas formas |
| librería de gráficos | **fuera de alcance** | Sin gráficas en esta fase; el presupuesto de paquete lo impide |

Ninguna dependencia nueva del lado de Python. `pyproject.toml` no cambia.

**Storage**: ninguno nuevo. El panel no persiste nada salvo la credencial en `sessionStorage`.

**Testing**: Vitest sobre `jsdom` para el panel, sin red ni API real. La suite de `pytest`
existente sigue igual y debe pasar sin cambios (FR-047).

**Target Platform**: navegadores actuales de escritorio y móvil. El `dist/` se sirve desde nginx en
Raspberry Pi 2B; la construcción ocurre en la máquina de desarrollo o en integración continua.

**Project Type**: aplicación web de una sola página en `frontend/`, más artefactos de despliegue.
El paquete de Python permanece intacto.

**Performance Goals**: paquete inicial **< 500 kB en bruto** y **< 150 kB transferidos**. Medido en
el andamiaje: 216,69 kB / 59,45 kB; compilación en 3,2 s; `dist/` de 256 kB. Un panel de tres
vistas debería quedar en 350-450 kB en bruto.

**Constraints**:

- El panel **no puede** accionar una salida: la API no lo permite, y no debe insinuar que exista.
- El estado sin confirmar **no puede** compartir apariencia con un estado confirmado, ni
  distinguirse solo por el color.
- La potencia instantánea **no se muestra** sin vigencia. Ni un cero.
- Las antigüedades vienen de la API, nunca del reloj del navegador.
- La credencial no persiste tras cerrar la pestaña ni aparece en la dirección de la página.
- El panel se compila fuera del dispositivo; en la Pi no se instala ninguna herramienta de
  construcción.
- La API sigue escuchando solo en `127.0.0.1`; no se configura ningún origen cruzado.
- Ningún test del panel usa red, navegador real ni la API real.

**Scale/Scope**: un operador, una instalación, tres vistas. Del orden de 4-10 acumuladores y un
histórico de un año consultado por páginas de 50.

## Constitution Check

*GATE: superado antes de Phase 0 y revisado tras Phase 1.*

### I. Seguridad física primero (fail-safe) — PASA

| Regla | Cómo se cumple |
| --- | --- |
| Ninguna interfaz activa una salida sin pasar por el controlador fail-safe | El panel **no tiene forma** de hacerlo: la API no expone ninguna operación de conmutación, y esta fase no añade ninguna. Verificable comprobando que el panel no llama a ninguna ruta que no exista |
| La ambigüedad se resuelve hacia el estado seguro | Sin vigencia, el panel dice «no lo sé»: no pinta ninguna salida como cargando y **no muestra potencia**. Un cero sería una afirmación; la ausencia de cifra no lo es |
| Nada oculta una situación peligrosa | Los minutos no atendidos se destacan (FR-015), y la sospecha de dos controladores produce una advertencia prominente, no una nota discreta (FR-013) |
| Cambios con consecuencia eléctrica, deliberados | Potencia máxima, pin y nivel activo exigen confirmación explícita que diga qué cambia (FR-020). Solo esos tres: pedir confirmación para todo enseña a confirmar sin leer |

### II. Núcleo puro, hardware y red en los bordes — PASA

- El panel es un borde nuevo y **completamente externo** al paquete de Python: vive en
  `frontend/`, con su propia cadena de herramientas.
- Consume exclusivamente la API por HTTP. No accede a la base de datos, ni a ficheros del
  dispositivo, ni a nada más.
- `src/dynamic_thermal_charge/` **no cambia en una sola línea**, y la suite existente debe seguir
  pasando sin modificaciones (FR-047).

### III. Configuración validada y explícita — PASA

- El panel **no reimplementa ni relaja** ninguna validación: valida para dar respuesta inmediata, y
  la API sigue siendo la autoridad (FR-023).
- La revisión viaja en cada escritura, y un conflicto se presenta y se ofrece releer, nunca se
  sobrescribe (FR-019).
- La credencial no se escribe en almacenamiento persistente ni en la dirección de la página
  (FR-003). Es el mismo principio que excluye los secretos del almacén de configuración, aplicado
  al navegador.
- El panel no puede migrar el esquema ni inicializar la base de datos, y cuando hace falta lo dice
  explícitamente en lugar de ofrecer un botón que no existe (FR-032).

### IV. Continuidad y degradación observable — PASA

- Esta fase es, en buena medida, **la observabilidad de la degradación hecha visible**: las cuatro
  situaciones del controlador se distinguen y cada anomalía orienta sobre qué comprobar (FR-012).
- Ante una API caída se conserva lo último mostrado, marcado como no actual: no se vacía la
  pantalla ni se deja cargando indefinidamente (FR-030).
- El refresco se detiene con la vista en segundo plano y se reanuda de inmediato al volver
  (FR-046), para no cargar gratuitamente al dispositivo que además ejecuta el bucle de control.

### V. Tests deterministas sin hardware — PASA

- Vitest sobre `jsdom`: sin red, sin navegador, sin la API real (FR-045). Medido: 1,02 s.
- La cobertura obligatoria se concentra donde el fallo miente al operador: la interpretación del
  estado sin confirmar (FR-044), el cálculo de antigüedades, el interceptor de la credencial, el
  conflicto de revisión y la traducción de cada error de la API.
- El arnés HTTP de Angular intercepta en memoria: ningún test abre un puerto ni depende de un
  servidor.

### VI. Simplicidad y stdlib primero — PASA

- **Cero dependencias nuevas de Python.** `pyproject.toml` no cambia.
- Del lado del panel, solo el marco y su cadena de herramientas. Sin librería de componentes, sin
  librería de gráficos, sin gestor de estado externo: las señales del marco bastan para tres
  vistas.
- `--zoneless` retira `zone.js`, es decir **menos** runtime que la configuración por defecto
  clásica.
- El presupuesto de paquete es el mecanismo que mantiene esto honesto: una dependencia añadida sin
  pensar falla la compilación.
- YAGNI respetado: sin gráficas, sin traducción a varios idiomas, sin funcionamiento sin conexión,
  sin instalación como aplicación, sin usuarios ni roles.

### Restricciones de plataforma — PASA

- **«Cualquier artefacto de frontend MUST compilarse fuera del dispositivo de despliegue»**: es
  exactamente lo que hace esta fase, y el instalador no instala Node ni ninguna herramienta de
  construcción en la Pi (FR-037).
- La constitución 1.1.0 ya prevé la interfaz web como borde; no hace falta enmienda.
- El dispositivo gana un componente nuevo, nginx, que se instala desde los paquetes del sistema.
  No requiere compilación.

**Resultado de la puerta: PASA.** Una desviación, registrada abajo.

## Project Structure

### Documentation (this feature)

```text
specs/003-web-panel/
├── plan.md              # Este fichero
├── spec.md
├── research.md          # Phase 0: 12 decisiones, con el andamiaje medido de verdad
├── data-model.md        # Phase 1: el modelo de vista y el tipo de tres estados
├── quickstart.md        # Phase 1: desarrollo, compilación, despliegue y diagnóstico
├── contracts/
│   ├── nginx.md         # El sitio, con sus invariantes y el bloque de cifrado
│   └── panel.md         # Las reglas que el panel garantiza al operador
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 — lo crea /speckit-tasks
```

### Source Code (repository root)

```text
frontend/                                   # NUEVO — espacio de trabajo de Angular
├── package.json, angular.json, tsconfig*.json
├── public/
└── src/
    ├── main.ts, index.html, styles.css
    └── app/
        ├── app.ts, app.config.ts, app.routes.ts
        ├── core/
        │   ├── api.ts                      # cliente de la API; el único que la conoce
        │   ├── api.types.ts               # tipos derivados del contrato de la fase 2
        │   ├── auth.ts                    # sesión: sessionStorage, nada persistente
        │   ├── auth.interceptor.ts         # añade la credencial; cierra sesión ante 401
        │   ├── errors.ts                   # código de la API -> explicación accionable
        │   ├── output-state.ts             # EL TIPO DE TRES VALORES + su derivación
        │   └── poll.ts                     # sondeo con parada en segundo plano
        ├── status/                          # vista de estado
        ├── config/                          # vista de configuración
        ├── history/                         # vistas de histórico
        └── shared/
            ├── output-indicator/            # tres apariencias, no dos, y no solo color
            ├── age/                         # antigüedad a partir de los datos de la API
            └── confirm/                     # confirmación para campos eléctricos

deploy/nginx/dynamic-thermal-charge.conf     # NUEVO — el sitio de contracts/nginx.md
scripts/install-service.sh                   # + opción --with-panel
README.md                                    # + sección del panel
tests/test_deployment.py                     # + verificación del sitio de nginx

src/dynamic_thermal_charge/                  # SIN CAMBIOS, ni una línea
```

**Structure Decision**: dos cadenas de herramientas separadas. `frontend/` tiene su propio
`package.json` y no se mezcla con el empaquetado de Python; `.gitignore` excluye
`frontend/node_modules` y `frontend/dist`.

`core/output-state.ts` merece existir como fichero propio aunque sea pequeño: es donde vive el tipo
de tres valores y la conversión desde la respuesta de la API, y es el punto del que depende que el
panel no mienta. Concentrarlo hace que se pueda probar como una función y que su modificación sea
visible en cualquier revisión.

## Verificación desde el lado de Python

Aunque el panel es externo, tres cosas se verifican desde la suite existente, porque son artefactos
del repositorio:

| Qué | Cómo |
| --- | --- |
| El sitio de nginx cumple sus invariantes | `tests/test_deployment.py`: `try_files` presente, `index.html` sin cachear, `proxy_pass` a `127.0.0.1`, cabecera de autorización propagada, bloque de cifrado presente y comentado |
| El instalador ofrece el panel sin forzarlo | no arranca ni habilita nada, y no instala Node |
| `src/` no ha cambiado | la suite completa de Python pasa sin modificaciones |

## Complexity Tracking

| Violación | Por qué es necesaria | Alternativa más simple rechazada porque |
| --- | --- | --- |
| Añadir una segunda cadena de herramientas completa —Node, npm, TypeScript, Angular— a un proyecto que era Python y stdlib (Principio VI) | La feature es, por definición, una interfaz de navegador. Mitigado: vive aislada en `frontend/`, **no añade ni una dependencia de Python**, no se instala nada de ella en el dispositivo, y `--zoneless` deja menos runtime que la configuración clásica | Servir HTML generado desde la API evitaría toda la cadena, pero un panel que refresca estado en vivo, edita formularios con validación por campo y pagina tablas acabaría siendo una aplicación de una sola página escrita a mano con JavaScript sin tipos ni pruebas. Para la superficie que informa sobre una instalación eléctrica, ese es el peor sitio para el código artesanal |
| Un componente nuevo en el dispositivo, nginx | Da un único origen al navegador —lo que hace innecesario configurar orígenes cruzados—, mantiene la API sin exponer, y abre la vía del cifrado que la fase anterior dejó como riesgo asumido. Se instala desde los paquetes del sistema, sin compilar | Que la API sirviera los estáticos ahorraría el componente, pero obligaría a exponerla en la red, le daría la responsabilidad de servir ficheros, y cerraría la vía del cifrado. Fue la decisión del usuario y resulta mejor que mi recomendación inicial |
| Un tipo de tres valores donde la API devuelve un campo anulable, más un componente dedicado a pintarlo | Es el mecanismo que impide que la distinción entre estado vigente y último estado conocido se pierda en la última pantalla. Sin él, la primera conversión a booleano la destruye en silencio | Un booleano con una bandera aparte de «es actual» es más corto y deja la puerta abierta a pintar el booleano olvidando la bandera, que es exactamente el fallo que la fase anterior existe para evitar. El comprobador de tipos no perdona; una convención sí |
