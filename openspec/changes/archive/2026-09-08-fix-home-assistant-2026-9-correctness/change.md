# Corregir la integración con Home Assistant actual

Status: approved

## Goal

Hacer que la integración nativa funcione correctamente con Home Assistant Core 2026.9.1, eliminar entidades y dispositivos obsoletos, endurecer la identidad y el transporte de la conexión y cubrir el ciclo de vida real de la integración con pruebas automatizadas.

## Requirements

- R1: El sensor de estado del controlador debe publicar `running`, `idle`, `degraded` y `error` como estados enum válidos de Home Assistant.
- R2: El calendario debe exponer el evento activo o el siguiente evento futuro, ordenar y fusionar los intervalos como hasta ahora y funcionar en cualquier fecha, incluido el 29 de febrero.
- R3: Cada snapshot confirmado debe añadir los acumuladores nuevos y retirar de Home Assistant tanto las entidades como el dispositivo de cada acumulador eliminado, sin afectar al controlador ni a otros acumuladores.
- R4: La reautenticación y la reconfiguración deben actualizar y recargar la entrada mediante las APIs actuales de Home Assistant y rechazar un endpoint o token cuyo UUID de instalación no coincida con el de la entrada.
- R5: El coordinador y el cliente deben almacenarse en `ConfigEntry.runtime_data`; los acumuladores deben enlazarse al controlador con la API actual basada en `via_device_id`, sin APIs deprecadas en Home Assistant 2026.9.1.
- R6: La configuración debe admitir HTTP y HTTPS conservando host y puerto separados. HTTPS debe validar el certificado; las entradas existentes sin protocolo deben migrarse explícitamente a HTTP sin cambiar su UUID ni sus entidades.
- R7: Un fallo de conexión, autenticación, validación TLS o respuesta incompatible debe producir el estado de configuración/no disponibilidad apropiado sin conservar datos como actuales ni exponer secretos en diagnósticos o logs.
- R8: El entorno de desarrollo debe fijar Home Assistant Core 2026.9.1 y las pruebas deben ejercitar configuración, reautenticación, reconfiguración, setup/unload, polling, comandos, calendario, entidades y reconciliación de dispositivos.
- R9: `README.md` debe documentar la instalación manual de la integración en Home Assistant, incluidos prerrequisitos, copia de `custom_components/dynamic_thermal_charge`, reinicio, alta desde la interfaz, conexión HTTP/HTTPS, actualización, desinstalación y una comprobación básica; también debe indicar la validación TLS, la migración de entradas HTTP existentes y la versión de Home Assistant soportada.

## Acceptance

- A1: Los cuatro estados del controlador se escriben sin excepción y con `SensorDeviceClass.ENUM`.
- A2: Sin evento activo, `calendar.event` devuelve el próximo; con uno activo devuelve ese; el cálculo no falla el 29 de febrero.
- A3: Al pasar de un inventario `{A, B}` a `{A}`, desaparecen todas las entidades y el dispositivo de `B`, mientras `A` y el controlador conservan sus identificadores.
- A4: Reautenticar o reconfigurar contra otro UUID se aborta sin modificar la entrada; con el mismo UUID se actualiza una sola entrada y se recarga una sola vez.
- A5: Setup, descarga y reconciliación usan `runtime_data` y `via_device_id` sin advertencias deprecadas bajo Home Assistant 2026.9.1.
- A6: HTTP y HTTPS válidos completan el flujo; un certificado inválido se rechaza; una entrada versión 1 migra a HTTP conservando identidad.
- A7: Siguiendo únicamente `README.md`, un usuario puede instalar, configurar, verificar, actualizar y desinstalar la integración en Home Assistant 2026.9.1.
- A8: Las pruebas específicas de la integración y `make check` pasan.

## Outcome

La integración nativa queda alineada con Home Assistant Core 2026.9.1, con transporte HTTP/HTTPS validado, ciclo de vida dinámico de dispositivos, disponibilidad segura y documentación de instalación. `make check` pasa completo.
