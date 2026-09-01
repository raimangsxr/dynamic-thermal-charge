# Centralizar la configuración de previsión en Sistema

Status: approved

## Goal

Hacer que `Sistema → weather` sea la única interfaz de configuración de
previsión y que el controlador utilice esos valores de forma coherente,
incluidos proveedor, municipio, credencial AEMET, simulación, fallback y
política de actualización.

## Requirements

- R1: La sección `weather` de configuración del sistema expondrá y persistirá proveedor, municipio AEMET, timeout, temperaturas simuladas, temperaturas de fallback y los intervalos de reintento y actualización.
- R2: El cambio a AEMET exigirá un código de municipio válido y una clave AEMET configurada; la clave nunca se devolverá al navegador.
- R3: El runtime construirá la configuración funcional de previsión desde la configuración del sistema y su secreto AEMET, sin depender de valores editables en la pantalla de configuración general.
- R4: La pantalla `Configuración` no ofrecerá campos ni edición de weather; la pantalla `Sistema` contendrá todos los controles de previsión.
- R5: Los valores enumerados, empezando por el proveedor (`AEMET`/`Simulado`), se editarán con dropdowns; el formulario agrupará el resto de campos y será usable sin overflow en anchos reducidos.

## Acceptance

- A1: Una configuración AEMET completa guardada desde `Sistema` puede ser cargada por el controlador sin producir `AEMET weather provider requires AEMET configuration`.
- A2: Una configuración AEMET sin municipio o sin secreto se rechaza atómicamente con un error accionable.
- A3: La API pública de configuración muestra solo si `aemet_api_key` está configurada y nunca su valor.
- A4: Las pruebas backend cubren el round-trip de todos los campos weather y la construcción runtime; las pruebas frontend cubren el dropdown, el envío del secreto y el layout responsive.

## Decisions

- D1: El nombre del secreto administrado por Sistema es `aemet_api_key`; `api_key_env` deja de ser un ajuste editable y se conserva internamente como `AEMET_API_KEY` para compatibilidad del dominio.
