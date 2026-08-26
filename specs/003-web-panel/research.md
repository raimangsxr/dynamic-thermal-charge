# Phase 0 — Research: Panel web de estado, configuración e histórico

**Feature**: `003-web-panel` | **Fecha**: 2026-08-26

Todas las mediciones se han tomado generando un andamiaje real de Angular 22.1.6 con Node
24.18.0 y npm 11.16.0, no estimadas.

---

## D1 — Angular 22 con componentes autónomos, señales y **sin `zone.js`**

**Decisión**: `ng new --standalone --zoneless --test-runner vitest --style css --routing`.
Detección de cambios basada en señales, sin `NgModule` y sin `zone.js`.

**Rationale**: verificado en el andamiaje generado:

- `--standalone` es ya el valor por defecto en Angular 22, así que no hay que decidirlo.
- `--zoneless` **retira `zone.js` de verdad**: comprobado que el paquete no queda instalado. Eso
  elimina el parcheado global de temporizadores y promesas, que es runtime que no queremos en un
  panel servido desde una tarjeta SD.
- El resultado compila y los tests pasan sin ningún ajuste manual.

Las dependencias que declara el andamiaje son mínimas y todas de Angular: `@angular/common`,
`compiler`, `core`, `forms`, `platform-browser`, `router`, más `rxjs` y `tslib`. En desarrollo:
`@angular/build`, `cli`, `compiler-cli`, `jsdom`, `prettier`, `typescript`, `vitest`.

**Alternativa descartada**: la configuración clásica con `NgModule` y `zone.js`. Más runtime, más
ceremonia, y con señales la detección explícita encaja mejor con un panel cuyo dato central —la
vigencia del estado— hay que recalcular de forma controlada.

---

## D2 — Ejecutor de pruebas: **Vitest**, que es ya el valor por defecto

**Decisión**: Vitest, sin Karma.

**Rationale**: consultada la ayuda real de `ng new` en Angular 22:

```text
--test-runner   The unit testing runner to use.
                [string] [choices: "karma", "vitest"] [default: "vitest"]
```

Vitest **es el valor por defecto**, no una opción experimental. Karma sigue disponible pero ya no
es la recomendación del propio marco.

Medido en el andamiaje: 2 tests en **1,02 s**, y **3,58 s** de reloj incluyendo el arranque del
proceso. Corre sobre `jsdom`, sin navegador que descargar ni lanzar, lo que satisface FR-045
—pruebas sin red y sin la API real— sin excepciones.

**Alternativa descartada**: Karma con un navegador headless. Más lento, un navegador que instalar
en la máquina de construcción, y desaconsejado ya por Angular.

---

## D3 — Sin librería de componentes: CSS propio

**Decisión**: no usar Angular Material ni ninguna otra librería de componentes. Un conjunto
pequeño de estilos propios.

**Rationale**: la interfaz son **tres vistas** —estado, configuración, histórico— con formularios
sencillos y tablas. Angular Material aporta un catálogo amplio de componentes que no vamos a usar,
y a cambio trae peso de paquete, un sistema de temas que hay que aprender y una capa más entre lo
que se escribe y lo que se pinta.

El argumento a favor de Material sería la accesibilidad de serie. Pero el requisito de
accesibilidad que de verdad importa aquí es **FR-036**, que la distinción entre estado confirmado
y sin confirmar no dependa del color, y eso ninguna librería lo resuelve: es una decisión de diseño
que hay que tomar a mano de todas formas.

**Alternativa descartada**: Angular Material. Se puede reconsiderar si la interfaz crece mucho,
pero añadirla ahora sería peso sin contrapartida.

---

## D4 — Presupuesto de paquete y de despliegue

**Decisión**: presupuesto declarado de **< 500 kB en bruto** y **< 150 kB transferidos** para el
paquete inicial. El `dist/` completo debe caber holgadamente en la tarjeta del dispositivo.

**Rationale**: medido sobre el andamiaje recién generado, compilado en producción:

| Medida | Valor |
| --- | ---: |
| tiempo de compilación en producción | 3,2 s (5,08 s de reloj) |
| paquete inicial, tamaño en bruto | 216,69 kB |
| paquete inicial, transferencia estimada | 59,45 kB |
| `dist/` completo | 256 kB |
| `node_modules` en la máquina de construcción | 253 MB |

Un panel de tres vistas debería quedar en torno a 350-450 kB en bruto y 100-130 kB transferidos.
El presupuesto tiene margen y es lo bastante estrecho para que un descuido —importar una librería
de gráficos «solo para probar»— falle la compilación en lugar de colarse.

**Medición real del panel terminado**, con las tres vistas y sus tests:

| Medida | Presupuesto | Real |
| --- | ---: | ---: |
| paquete inicial, en bruto | < 500 kB | **264,05 kB** |
| paquete inicial, transferido | < 150 kB | **74,00 kB** |
| `dist/panel/browser/` completo | — | 372 kB |
| `main` (sin las vistas, que van diferidas) | — | 96,41 kB / 24,64 kB |

Quedó por debajo incluso de la estimación: las tres vistas se cargan en fragmentos diferidos, así
que el arranque solo trae el armazón, el acceso y lo compartido. Verificado además que el
presupuesto **sabe fallar**, bajándolo temporalmente a 10 kB: la compilación se detuvo con
«bundle initial exceeded maximum budget».

Los 253 MB de `node_modules` viven **solo en la máquina de construcción**. En el dispositivo se
copian 256 kB de ficheros estáticos y nada más: es la razón por la que compilar fuera no es una
incomodidad sino la única opción sensata.

---

## D5 — La estrategia de caché sale del propio nombre de los ficheros

**Decisión**: en el servidor web del dispositivo, los ficheros con huella en el nombre se sirven
como inmutables y con caducidad larga; `index.html` se sirve con `no-cache`.

**Rationale**: inspeccionado el `dist/` real generado:

```text
index.html                 419 bytes     <- sin huella
main-DBJQ7CUN.js       216 685 bytes     <- con huella
styles-5INURTSO.css         0 bytes      <- con huella
favicon.ico             15 086 bytes     <- sin huella
```

La compilación pone una huella en el nombre de cada recurso cuyo contenido puede cambiar, y deja
`index.html` sin huella porque es el punto de entrada que apunta a los demás. Eso resuelve FR-041
sin inventar nada:

- Recursos con huella: `Cache-Control: public, max-age=31536000, immutable`. Su nombre cambia
  cuando cambia el contenido, así que un navegador nunca puede servir una versión vieja.
- `index.html`: `Cache-Control: no-cache`. Se revalida siempre, y es lo que hace que una versión
  nueva se recoja sin borrar la caché a mano.

Cachear `index.html` es precisamente el error que produce el fallo clásico: el operador actualiza,
recarga, y sigue viendo la interfaz antigua porque su navegador conserva un `index.html` que
apunta a los recursos viejos.

---

## D6 — nginx: un solo origen, y la API que no se expone

**Decisión**: nginx en el dispositivo sirve el `dist/` y hace de intermediario hacia la API en
`127.0.0.1:8420`. Un fichero de configuración de sitio versionado en el repositorio, con un bloque
de cifrado comentado.

**Rationale**: es la consecuencia más valiosa de la decisión del usuario. Con nginx delante:

- El navegador ve **un único origen**, así que no hay orígenes cruzados que configurar y
  `DTC_API_CORS_ORIGINS` puede quedarse vacío, que es su valor por defecto y el más seguro.
- La API **sigue escuchando solo en la interfaz local**. nginx es el único componente expuesto en
  la red, y eso es exactamente lo que FR-039 exige.
- Queda abierta la vía del cifrado en tránsito, que es el hueco que la fase anterior documentó
  como riesgo asumido. No se activa en esta fase, pero el sitio lleva el bloque preparado y
  comentado.

Tres detalles que la configuración debe resolver y que son fáciles de olvidar:

1. **Recarga de rutas internas** (FR-040): `try_files $uri $uri/ /index.html;`. Sin esto, recargar
   una dirección interna del panel devuelve 404, porque en el disco no existe ese fichero.
2. **La cabecera de autorización** debe llegar íntegra a la API. nginx no la elimina por defecto,
   pero conviene declararlo para que un cambio futuro no la rompa en silencio.
3. **Caché diferenciada** según D5, por ubicación.

**Alternativa descartada**: que la API sirviera los estáticos. Un proceso menos, pero obligaría a
exponer la API en la red, le daría la responsabilidad de servir ficheros, y perdería la vía del
cifrado. El usuario eligió nginx y sale mejor.

---

## D7 — La credencial: en `sessionStorage`, y en un interceptor

**Decisión**: la credencial vive en `sessionStorage`. Un interceptor de peticiones la añade a
cada llamada a la API y trata el rechazo por credencial cerrando la sesión.

**Rationale**: `sessionStorage` sobrevive a recargar la página y muere al cerrar la pestaña, que
es literalmente lo que pide FR-002. `localStorage` la dejaría indefinidamente en el equipo y
`memoria` obligaría a reintroducirla en cada recarga.

El interceptor es el único sitio donde se lee la credencial, y es también el único sitio donde hay
que tratar el 401. Ponerlo en cada llamada garantizaría olvidarse en alguna.

**Lo que la credencial nunca hace** (FR-003): no aparece en la dirección de la página ni en
parámetros de consulta. Va siempre en la cabecera. Un token en la dirección quedaría en el
historial del navegador y en los registros de nginx.

---

## D8 — Tres estados de salida, obligados por el tipo

**Decisión**: modelar el estado de una salida como un tipo de **tres** valores, no como un
booleano. El compilador rechaza el código que trate `sin confirmar` como `apagado`.

**Rationale**: es el corazón de la historia 2 y el punto donde el trabajo de la fase anterior se
puede perder en la última pantalla. La API devuelve `output_on` como `true`, `false` o **`null`**,
y `null` significa «no tengo prueba», no «apagado».

Un booleano en el modelo del panel colapsaría `null` en `false` en la primera conversión, y a
partir de ahí la información estaría perdida sin que nada avisara. Con un tipo de tres valores, el
comprobador de tipos obliga a decidir explícitamente qué se pinta en el tercer caso, en cada sitio
donde se pinta.

Consecuencia para la presentación (FR-011, FR-036): tres apariencias distinguibles **sin depender
del color**, es decir con forma o texto además del color.

---

## D9 — Las antigüedades vienen de la API, no del reloj local

**Decisión**: mostrar la antigüedad del latido usando el `age_seconds` que da la API, y los
instantes que da la API, nunca una diferencia calculada contra el reloj del navegador.

**Rationale**: FR-016. El equipo que muestra el panel —un móvil, un portátil— y la Raspberry Pi
pueden tener relojes distintos, y la Pi no tiene reloj con batería. Calcular «hace 3 segundos»
como `Date.now() - last_seen_at` produciría edades negativas o de horas según la desviación, justo
en el indicador del que depende que el operador confíe o no en lo que ve.

La API ya calcula la antigüedad contra su propio reloj, que es el mismo con el que se escribió el
latido. Esa es la cifra correcta y la única coherente.

---

## D10 — Refresco: sondeo con parada en segundo plano

**Decisión**: sondeo periódico del estado, con una cadencia por defecto del orden de segundos,
que **se detiene** cuando el documento no está visible y se reanuda de inmediato al volver.

**Rationale**: FR-046. Una pestaña olvidada consultando cada pocos segundos durante días es carga
gratuita sobre un Cortex-A7 que además está ejecutando el bucle de control. La visibilidad del
documento es la señal estándar y no requiere nada especial.

Al volver al frente se refresca **inmediatamente**, no en el siguiente tick: volver a una pestaña
y ver datos de hace horas sin aviso sería peor que no refrescar.

El refresco no debe perder la posición de lectura ni el foco (FR-008), lo que descarta volver a
crear la vista en cada tick.

---

## D11 — Pruebas sin red ni API real

**Decisión**: tests unitarios con Vitest y el arnés de pruebas HTTP de Angular, que intercepta las
peticiones en memoria. Sin servidor, sin red, sin navegador.

**Rationale**: FR-045. Verificado que el andamiaje corre sobre `jsdom` en 1 s.

Lo que hay que cubrir con más cuidado, por orden de consecuencia si falla:

1. **La interpretación del estado sin confirmar** (FR-044): la tabla completa de las cuatro
   situaciones del controlador, y que en ninguna de las dos no vigentes se presente una salida
   como encendida ni se muestre potencia.
2. **El cálculo de antigüedades** a partir de los datos de la API, no del reloj local.
3. **El interceptor**: que añade la credencial, que no la pone en la dirección, y que cierra la
   sesión ante un rechazo.
4. **El conflicto de revisión**: que se avisa y se ofrece releer, y que no se reintenta solo.
5. **La traducción de cada código de error de la API** a una explicación accionable.

Fuera de alcance: pruebas en navegador real. Otro toolchain, descargas de navegadores y tests más
frágiles, para una interfaz de tres vistas.

---

## D12 — Dónde vive el panel, y qué no toca

**Decisión**: un espacio de trabajo de Angular en `frontend/`, en la raíz del repositorio, con su
propio `package.json`. No se mezcla con el empaquetado de Python.

**Rationale**: son dos cadenas de herramientas distintas con dos gestores de dependencias
distintos, y mezclarlas complica ambas. `frontend/` queda claramente separado, y `.gitignore`
excluye `frontend/node_modules` y `frontend/dist`.

Nada de `src/dynamic_thermal_charge/` cambia en esta fase. La API ya expone todo lo necesario y
FR-045 de la fase anterior —que la API no sirve ficheros estáticos— **sigue siendo cierto**,
porque los sirve nginx. La suite de Python existente debe seguir pasando sin tocar una línea
(FR-047), y los artefactos nuevos son: el espacio de trabajo del panel, la configuración de nginx,
la opción del instalador y la documentación.
