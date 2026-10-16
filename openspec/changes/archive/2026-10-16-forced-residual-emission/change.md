# Emisión residual forzada del acumulador

Status: approved

## Goal
Modelar que un acumulador cargado pierde calor por la carcasa hacia su estancia aunque la descarga esté apagada. Hoy la emisión residual solo es un suelo de capacidad que el plan usa si decide emitir, y la calibración atribuye calor cero cuando la descarga está apagada; ambas cosas sobrestiman la energía disponible más tarde y sesgan el coeficiente de pérdida calibrado. La energía que queda al final del horizonte no es calor desperdiciado sino emisión futura no controlada, y así debe explicarse.

Depende de `automatic-thermal-calibration` para el ajuste de calibración (R6).

## Requirements
- R1: En cada intervalo el acumulador emite de forma forzada `P_residual × SOC_inicio × duración`, con `P_residual = static_emission_percent × P_emisión`, limitada por la energía disponible tras la carga del intervalo; un acumulador vacío no emite.
- R2: Con la descarga habilitada, el calor total del intervalo puede crecer hasta el límite actual `(P_residual + (P_emisión − P_residual) × SOC_inicio) × duración`; sin descarga, el calor total es exactamente la emisión forzada. Este calor forzado también se produce en intervalos sin consigna activa ni posterior, sustituyendo la regla actual de calor cero.
- R3: Planificador, validación independiente por replay, desviación y estimador de demanda usan la misma función de paso, y un plan cuya reproducción no reproduce la emisión forzada es `INVALID`.
- R4: La descarga MQTT se habilita solo cuando el plan proyecta calor controlado, es decir, calor total por encima del forzado; la emisión forzada sola no publica activación ni consigna.
- R5: La auditoría física, la explicación y el detalle por intervalo separan calor forzado y calor controlado; los planes anteriores muestran el calor forzado como no disponible.
- R6: El ajuste de calibración atribuye en cada intervalo la emisión forzada más, cuando la descarga está habilitada, la emisión controlada modelada por compuerta; las fases sin descarga dejan de suponer calor cero.
- R7: La explicación del plan presenta la energía final como calor que se liberará después del horizonte, indicando cuánta se emitirá de forma forzada, y la carga `residual_storage` se describe en esos términos.
- R8: La ayuda de `static_emission_percent` explica que es la fuga continua a carga completa y su efecto en planificación y calibración.

## Acceptance
- A1: Pruebas del paso físico: con descarga apagada y SOC positivo la estancia recibe exactamente el calor forzado; con SOC cero recibe cero; con descarga habilitada el calor nunca supera el límite vigente.
- A2: Pruebas del planificador: un intervalo sin consigna por delante recibe calor forzado y no cero; el validador rechaza un candidato al que se elimina ese calor.
- A3: Pruebas de desviación y estimador reproducen el mismo calor forzado que el plan persistido.
- A4: Pruebas de descarga MQTT: emisión solo forzada publica desactivación y `NULL`; calor controlado positivo publica activación y consigna.
- A5: Pruebas de explicación y API muestran calor forzado, calor controlado y energía final explicada; un plan histórico muestra el calor forzado como no disponible.
- A6: Fixtures de calibración con fuga simulada recuperan los coeficientes dentro de la tolerancia de calidad que sin este cambio no alcanzaban.

## Outcome
Implementado y verificado; `make check` pasó una vez tras el último cambio verificable (1052 backend, 282 frontend, build/lint/compose).
