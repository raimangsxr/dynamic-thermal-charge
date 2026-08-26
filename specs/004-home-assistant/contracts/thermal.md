# Contract — El modelo térmico con temperatura interior

**Feature**: `004-home-assistant`

El único cambio de esta fase en el núcleo del proyecto. Merece contrato propio porque toca el
componente que decide cuánta energía se pide.

## Frontera

```text
ThermalDemandEngine.calculate(
    heaters,
    forecast,
    indoor: Mapping[str, IndoorReading] | None = None,   <- NUEVO, opcional
) -> dict[str, int]
```

Sigue siendo una **función determinista sin I/O**. Las medidas llegan como parámetro; el modelo no
lee nada, no consulta nada y no conoce MQTT. Quien las recoge es el publicador (Principio II).

## El cálculo

```text
rango = objetivo - exterior_de_diseño            (sin cambios)

sin medida utilizable:
    déficit = objetivo - exterior_prevista        [COMPORTAMIENTO ANTERIOR]
con medida utilizable:
    déficit = objetivo - interior_medida

fracción = (déficit / rango) × factor_térmico
fracción = min(max_carga, max(min_carga, fracción))   (sin cambios)
minutos  = round(minutos_carga_completa × fracción)   (sin cambios)
```

Solo cambia el origen del déficit. El denominador, el factor y los límites son los de siempre.

## Cuándo una medida es utilizable

```text
el acumulador no declara origen de temperatura  -> NO   (y es el caso por defecto)
no hay medida para ese acumulador               -> NO
antigüedad > indoor_max_age_minutes             -> NO
celsius fuera de [min_plausible, max_plausible] -> NO, y se registra como ERROR
en otro caso                                    -> SÍ
```

«NO» significa **el comportamiento anterior a esta fase**, no un valor por defecto inventado.

## Tres garantías no negociables

**1. Un acumulador sin origen declarado calcula *exactamente* lo mismo que antes.**

Es FR-023 y es lo que hace que la fase no cambie nada para quien no la use. Merece un test que
compare la demanda calculada antes y después con la misma entrada, no una comprobación por
inspección.

**2. Una estancia que ya alcanzó su objetivo pide el mínimo configurado, no cero.**

El numerador se vuelve negativo, y eso es **correcto**: los límites lo recortan a `min_charge`. El
mínimo existe por acumulador y tiene una razón física, conservar algo de reserva térmica. Va
comentado en el código para que nadie «arregle» el negativo.

**3. Ningún fallo de temperatura interior impide generar el plan.**

Una medida ausente, vieja o absurda produce reserva y un registro, nunca una excepción. El
planificador tiene que seguir produciendo un plan, y ninguna salida puede quedar en estado
indeterminado (FR-027, Principio I).

## Registro

La entrada y la salida del uso de la reserva se registran **una sola vez en cada transición**,
nunca en cada cálculo. Es la misma disciplina del watchdog meteorológico y de la degradación por
base de datos, y por la misma razón: un registro por iteración es ruido que oculta la señal.

Lo que se registra:

- al empezar a usar la reserva para un acumulador, con el motivo —sin medida, vieja, o fuera de
  rango—;
- al volver a usar medidas reales;
- cada valor descartado por implausible, como error, porque eso indica un sensor averiado y no una
  ausencia normal.
