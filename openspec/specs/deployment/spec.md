## Purpose

Mantener la configuración GPIO de producción alineada con el dispositivo del
host y evitar despliegues que no puedan acceder a él.

## Requirements

### Requirement: Identidad aislada de Compose en desarrollo

Los comandos Compose de desarrollo deben derivar una identidad de proyecto
estable, válida y específica de cada checkout. Las variantes SQLite y
PostgreSQL, así como parada y limpieza, deben reutilizar esa identidad; la
configuración de producción conserva sus nombres y volúmenes explícitos.

#### Scenario: Dos checkouts simultáneos

- **WHEN** se levantan dos worktrees del repositorio
- **THEN** cada uno usa contenedores, redes y volúmenes propios y detener uno no afecta al otro

### Requirement: Artefactos de entrega reproducibles

Las imágenes de producción deben instalar dependencias desde locks versionados,
usar bases inmutables y publicar metadatos que relacionen el artefacto con su
commit y locks. El backend debe conservar una ruta verificable para ARMv7 sin
toolchain de compilación en la imagen final.

#### Scenario: Repetición de un build

- **WHEN** se construye dos veces el mismo commit con la misma configuración
- **THEN** se resuelven las mismas dependencias y bases y los checks de entrega verifican sus metadatos

### Requirement: Preflight y GID GPIO autoritativo

El reconciliador debe comprobar que `/dev/gpiochip0` existe como dispositivo de
caracteres y derivar de su propiedad el GID que recibe el backend antes de
resolver o aplicar Compose. Si el dispositivo no existe o un `DTC_GPIO_GID`
explícito no coincide con ese GID, el despliegue debe fallar explicando la
condición que hay que corregir.

#### Scenario: Dispositivo GPIO ausente

- **WHEN** se ejecuta el reconciliador sin `/dev/gpiochip0` o con un objeto que no es un dispositivo de caracteres
- **THEN** termina con error antes de aplicar Compose e indica que el dispositivo debe estar disponible

#### Scenario: GID del dispositivo actualizado

- **WHEN** cambia el GID propietario de `/dev/gpiochip0`
- **THEN** el reconciliador usa el GID actual en la configuración efectiva del backend

### Requirement: Reconciliación sin cambio de release

Cada ejecución debe aplicar una reconciliación idempotente de Compose aunque la
release de la imagen no haya cambiado. La descarga de imágenes solo se realiza
cuando cambia la release.

#### Scenario: Release sin cambios y GID actualizado

- **WHEN** la release deseada coincide con la imagen en ejecución y el GID GPIO ha cambiado
- **THEN** se aplica Compose para actualizar la configuración del backend sin descargar imágenes

### Requirement: GID explícito en Compose de producción

La configuración Compose de producción debe exigir `DTC_GPIO_GID`; no debe
resolver un GID predeterminado cuando la variable falta.

#### Scenario: Variable GPIO ausente

- **WHEN** se valida la configuración Compose de producción sin `DTC_GPIO_GID`
- **THEN** la validación falla y no selecciona un GID alternativo
