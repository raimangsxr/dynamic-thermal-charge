# Contract — Configuración de temperatura interior

**Feature**: `004-home-assistant`

Este contrato amplía las interfaces de configuración de las fases 1–3. No añade un endpoint ni
una vía de escritura nueva: los campos usan `ConfigRepository.set_field`, la revisión optimista y
los mismos errores existentes.

## Campos de instalación

| Nombre externo | Tipo de lectura | Escritura | Regla |
| --- | --- | --- | --- |
| `indoor_max_age_minutes` | entero | cadena que representa entero | `> 0`; por defecto `30` |
| `indoor_min_plausible_c` | número | cadena que representa número | por defecto `-20`; menor que el máximo |
| `indoor_max_plausible_c` | número | cadena que representa número | por defecto `50`; mayor que el mínimo |

Los tres aparecen en la raíz de `ConfigResponse` y se escriben con el endpoint existente de campo
de instalación, enviando siempre la revisión leída.

## Campo por acumulador

| Nombre externo | Tipo de lectura | Escritura | Regla |
| --- | --- | --- | --- |
| `indoor_topic` | cadena o nulo | cadena | asunto MQTT no vacío, o cadena vacía para eliminarlo |

`indoor_topic` aparece en `HeaterResponse` y en `AddHeaterRequest`. En cualquier interfaz, una
cadena vacía se normaliza a `null`; no se almacena como asunto vacío. Eliminarlo hace que el
acumulador vuelva exactamente al cálculo anterior y retira la suscripción en el siguiente refresco
de configuración.

## CLI

```bash
dtc config set indoor_max_age_minutes 30
dtc config set indoor_min_plausible_c -20
dtc config set indoor_max_plausible_c 50
dtc config set indoor_topic ha/sensor/temperatura_salon/state --heater salon
dtc config set indoor_topic '' --heater salon       # eliminar el origen
```

## API HTTP

Usa los endpoints y cuerpos de `specs/002-config-api/contracts/http-api.md`:

```json
{
  "revision": 12,
  "field": "indoor_topic",
  "value": ""
}
```

El éxito devuelve el cambio con `new_value: null`. Un rango incoherente o una tolerancia no
positiva devuelve el error de validación existente, asociado al campo, sin aplicar parcialmente.

## Panel

El formulario muestra los tres campos de instalación y `indoor_topic` dentro de cada acumulador.
Dejar el asunto vacío solicita su eliminación. El panel conserva la revisión optimista, presenta
el rechazo junto al campo y no reintenta automáticamente un conflicto.
