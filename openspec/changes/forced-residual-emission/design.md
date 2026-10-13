# Design

## Approach
Introducir en el dominio una única descomposición del calor por intervalo, `forced_heat_kwh` y `controlled_heat_kwh`, y hacer que `room_energy_step` la devuelva. `forced = min(P_residual × SOC_inicio × dt, E + carga)`; `controlled ∈ [0, límite − forced]` y solo si la descarga está permitida. El MILP conserva la variable `heat_delivered` y añade una cota inferior `heat ≥ P_residual × dt × stored_energy / capacidad`, que es lineal porque el SOC de inicio es la energía almacenada del borde; la cota superior existente no cambia. En los intervalos sin consigna por delante, la restricción actual `heat = 0` pasa a `heat = forced`.

El validador por replay deriva `forced` desde el SOC reproducido y exige que el calor del candidato no sea inferior a él ni lo supere cuando la emisión no está permitida. La desviación y el estimador ya usan `room_energy_step`, así que heredan la física; su reproyección con decisiones de carga persistidas debe incluir el calor forzado en todos los intervalos.

## Constraints
- La cota inferior se evalúa con la energía del borde inicial, igual que la cota superior, para mantener el modelo lineal y el replay determinista.
- `automatic_plan_slot` guarda cada magnitud por acumulador en columnas JSON; el calor forzado necesita una columna nueva `forced_heat_json` con `server_default` "{}" en la siguiente revisión Alembic libre, que se fija al implementar porque la calibración ocupa 0025.
- La calibración solo existe en `raimangsxr/thermal-calibration`; T5 se implementa apilado sobre esa rama o después de su merge.

## Decisions
- `mqtt/discharge.py` compara `controlled_heat_kwh` con `HEAT_EPSILON_KWH` en lugar del calor total, porque con la fuga casi todo intervalo con SOC positivo tendría calor mayor que cero.
- Los objetivos de calidad del optimizador siguen operando sobre calor total; el calor forzado es inevitable y no debe penalizarse como "calor prematuro". El componente `premature_heat` se calcula sobre calor controlado.
- El ajuste de calibración usa `forced + controlled × descarga × compuerta` por muestra, evaluado con el SOC de punto medio como hoy; la compuerta no limita la fuga.
- La explicación calcula la emisión forzada posterior al horizonte como la energía final y la presenta sin simular más allá del horizonte.

## Risks
- El 20 % por defecto puede sobrestimar la fuga de modelos bien aislados y adelantar déficits. Mitigación: ayuda explícita, efecto visible en el detalle y recalibración, que ahora absorbe la fuga correctamente.
- Cambia la factibilidad de planes con poca holgura: la fuga nocturna puede sobrecalentar estancias sin consigna, que el modelo no penaliza. Mitigación: pruebas con corpus de planes existentes comparando energía cargada y déficits.
- Planes y previews anteriores dejan de reutilizarse por el cambio de versión de token. Es intencionado.
