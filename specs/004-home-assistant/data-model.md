# Phase 1 — Data Model: Integración con Home Assistant

**Feature**: `004-home-assistant` | **Fecha**: 2026-08-27

Esta fase añade **columnas** a dos tablas existentes y una migración, `0003`. No añade tablas.

Es también la primera fase desde la 1 que **toca el núcleo**: el modelo térmico gana un parámetro.

---

## Columnas nuevas

### `heater`

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `indoor_topic` | texto | sí | Origen de la temperatura interior de la estancia. **Nulo por defecto** |

**Nulo por defecto es el requisito, no una comodidad.** FR-023 exige que un acumulador sin
temperatura declarada se comporte *exactamente* como antes de esta fase, y la forma de garantizarlo
es que la migración no cambie el valor efectivo de nada.

### `installation`

| Columna | Tipo | Nulo | Reglas |
| --- | --- | :---: | --- |
| `indoor_max_age_minutes` | entero | no | > 0. Por defecto **30**. Más allá, una medida se trata como ausente |
| `indoor_min_plausible_c` | real | no | Por defecto **-20**. Por debajo, se descarta con error |
| `indoor_max_plausible_c` | real | no | Por defecto **50**. Por encima, se descarta con error |

Restricción: `indoor_min_plausible_c < indoor_max_plausible_c`.

**Por qué 30 minutos**: una temperatura interior cambia despacio, así que media hora sigue siendo
informativa; seis horas no lo es, y usarla sería peor que no tener ninguna. El valor es
configurable porque depende de con qué frecuencia publique cada instalación.

**Por qué un rango de plausibilidad**: un sensor que se estropea no suele dejar de publicar, suele
publicar basura. Un `-127` o un `85` son valores típicos de un sensor de un cable roto, y
alimentar el planificador con ellos produciría una carga completamente equivocada en una dirección
o en la otra.

---

## Migración `0003_indoor_temperature`

Añade las cuatro columnas. No toca datos existentes. Los valores por defecto son los de arriba, de
modo que una instalación migrada **calcula exactamente lo mismo que antes** hasta que alguien
declare un `indoor_topic`.

Consecuencia para la puerta de versión: `KNOWN_REVISIONS` pasa a tener tres entradas, y una base de
datos de la fase 2 o 3 se detecta como **pendiente de migrar**, no como desconocida.

---

## Medida de temperatura interior

No se persiste. Vive en memoria en el proceso publicador, que es quien la recibe.

```text
IndoorReading
  heaterId       str
  celsius        float
  receivedAt     instante en que ESTE dispositivo la recibió
```

**`receivedAt` es del dispositivo, no del mensaje** (FR-026). El mensaje puede traer una fecha y
**no se usa**: es la tercera vez que esta lección aparece en el proyecto —el latido en la fase 2,
las antigüedades en la fase 3— y aquí una fecha desfasada haría pasar por reciente una medida
vieja, que es exactamente el fallo que la reserva existe para evitar.

### Cuándo una medida sirve

```text
sin medida para ese acumulador          -> reserva
receivedAt más antiguo que la tolerancia -> reserva
celsius fuera del rango plausible        -> se DESCARTA con error, y reserva
en otro caso                             -> se usa
```

«Reserva» significa el comportamiento anterior a esta fase, no un valor por defecto inventado.

---

## El cambio en el modelo térmico

```text
ANTES (y sigue siendo el caso sin medida):
    fracción = (objetivo - exterior_prevista) / (objetivo - exterior_de_diseño)

CON medida válida:
    fracción = (objetivo - interior_medida) / (objetivo - exterior_de_diseño)

EN AMBOS CASOS, después:
    fracción = fracción × factor_térmico
    fracción = min(max_carga, max(min_carga, fracción))
```

El denominador no cambia: sigue siendo el rango de diseño de la estancia. Lo que cambia es de dónde
sale el déficit — de una previsión exterior a una medida interior.

**Una estancia que ya alcanzó su objetivo produce un numerador negativo, y eso es correcto.** Los
límites lo recortan al `min_charge` configurado, que es lo que FR-029 pide: la carga mínima, no
cero. El mínimo existe por acumulador y tiene una razón física, conservar algo de reserva térmica.
Merece un comentario en el código para que nadie «arregle» el negativo.

El modelo sigue siendo una **función determinista sin I/O** (FR-028): las medidas llegan como
parámetro, nunca leídas por él.

---

## Estado de reserva térmica

No se persiste. Es la memoria de si el modelo está usando medidas reales o ha vuelto al
comportamiento anterior, y existe solo para registrar la **transición** y no cada cálculo (FR-025).

Es la misma disciplina que el estado degradado del watchdog meteorológico y el de la base de datos:
lo que se registra es entrar y salir, no cada iteración.

---

## Entidades publicadas

No se persisten. Son la proyección de lo que ya existe.

### Por acumulador

| Entidad | Tipo en el destino | Depende de ver al controlador |
| --- | --- | :---: |
| salida activa | binario | **sí** |
| potencia nominal | numérica | no |
| habilitado | conmutador **escribible** | no |
| carga objetivo | numérica **escribible** | no |
| minutos solicitados / asignados / **no atendidos** | numéricas | no |
| temperatura interior en uso | numérica | no |
| usando reserva térmica | binario | no |

### Por instalación

| Entidad | Tipo | Depende de ver al controlador |
| --- | --- | :---: |
| potencia instantánea total | numérica | **sí** |
| porcentaje del límite | numérica | **sí** |
| límite configurado | numérica | no |
| inicio y fin de la ventana del plan | instantes | no |
| temperatura media prevista | numérica | no |
| origen de la previsión | texto | no |
| salud del controlador | texto de cuatro valores | no |
| **más de un controlador sospechado** | binario | no |

La columna de la derecha es lo que decide qué se marca no disponible cuando el controlador no está
visible. La configuración sigue siendo perfectamente conocida —está en la base de datos— y sus
entidades siguen disponibles; solo lo que depende de ver al controlador deja de estar.

### Identificadores

Estables entre reinicios y derivados de la instalación y del identificador de dominio del
acumulador, nunca de una clave interna ni de un orden (FR-007). Si cambiaran, las automatizaciones
ya escritas dejarían de funcionar sin ningún aviso.

---

## Disponibilidad, en dos niveles

```text
Nivel 1  publicador vivo      <- respaldado por la ÚLTIMA VOLUNTAD ante el broker
Nivel 2  estado vigente       <- refleja si el controlador está visible

Entidades que dependen de ver al controlador: exigen AMBOS niveles.
Las demás:                                    exigen solo el nivel 1.
```

Un solo nivel no basta, y las dos formas de fallar son distintas:

| Qué falla | Con un solo nivel | Con los dos |
| --- | --- | --- |
| El publicador muere o cae el túnel | el último valor queda congelado para siempre | todo no disponible |
| El controlador muere, el publicador vive | se publicaría «apagado» sin prueba | las de salida no disponibles; la configuración sigue visible |

---

## Órdenes admitidas

**Lista blanca de dos campos**, no lista negra:

| Campo | Entidad | Efecto |
| --- | --- | --- |
| `enabled` | conmutador | habilita o deshabilita el acumulador |
| `target_charge` | numérica | cambia la fracción de carga solicitada |

Todo lo demás se rechaza y se registra. Una lista negra dejaría fuera cualquier campo futuro **por
omisión**; una lista blanca lo deja fuera **por defecto**, que es la dirección correcta para un
canal que atraviesa un túnel.

Los tres campos con consecuencias eléctricas —potencia máxima, pin, nivel activo— quedan fuera del
alcance de Home Assistant por construcción, no por comprobación.

Una orden rechazada **devuelve la entidad al valor realmente almacenado** (FR-018). Sin eso, Home
Assistant se quedaría mostrando el valor que ordenó y que nunca se aplicó, que es la forma más
silenciosa de mentir en una integración.
