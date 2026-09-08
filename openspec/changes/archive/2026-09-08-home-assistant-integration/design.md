# Design

## Durable design

- El backend conserva el UUID de instalación, el control automático, los modos de acumulador y las generaciones de recálculo. La API no conmuta drivers: el controlador consume ese estado durable en su ciclo normal.
- Un snapshot autenticado y versionado contiene la salud, el inventario, la telemetría y el resumen del plan; el forecast completo permanece en una operación separada.
- Home Assistant usa una sesión HTTP asíncrona y un coordinador compartido con polling de 30 segundos. Los comandos fuerzan actualización y aplican revisión optimista.
- Las entidades leen solo el snapshot en memoria. El inventario se reconcilia dinámicamente y las bajas solo se aplican después de una respuesta autoritativa exitosa.
- Los identificadores derivan del UUID de instalación y del identificador estable del acumulador; el token se limita a la entrada/cabecera y se redacta en diagnósticos y logs.
- El calendario fusiona únicamente slots contiguos del mismo acumulador y expone extremos con zona horaria, SOC y energía cuando están disponibles.

## Verification constraints

- SQLite y PostgreSQL conservan el mismo contrato mediante la migración del proyecto.
- Los fallos de transporte o autenticación marcan las entidades no disponibles sin mostrar datos antiguos; la recuperación se produce con el siguiente refresh válido.
- Home Assistant se fija en la versión de desarrollo compatible y su ejecución queda integrada en `make setup/test/lint/check`, sin entrar en la imagen del backend.
