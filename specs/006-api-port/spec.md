# Feature Specification: Cambiar puerto del API

**Feature Branch**: `006-api-port`
**Created**: 2026-08-28
**Status**: Ready
**Input**: User description: "Cambiar el puerto del API del 8420 al 8080"

## User Scenarios & Testing

### User Story 1 - API accesible en el nuevo puerto (Priority: P1)

Como operador, quiero que el API escuche por defecto en el puerto 8080 para que el servicio use el nuevo punto de acceso.

**Independent Test**: Ejecutar el API sin `DTC_API_PORT` y verificar que el servidor se inicia con el puerto 8080.

**Acceptance Scenarios**:
1. **Given** que `DTC_API_PORT` no está definido, **When** se inicia el API, **Then** escucha en `127.0.0.1:8080`.
2. **Given** una configuración explícita de `DTC_API_PORT`, **When** se inicia el API, **Then** se conserva ese valor explícito.

### Edge Cases

- Los proxies de desarrollo y producción deben dirigir al mismo puerto por defecto.
- La documentación y las pruebas no deben seguir presentando 8420 como puerto predeterminado.

## Requirements

### Functional Requirements

- **FR-001**: El API MUST usar 8080 como puerto predeterminado.
- **FR-002**: El sistema MUST conservar `DTC_API_PORT` como sobrescritura explícita.
- **FR-003**: Los proxies, ejemplos de despliegue, documentación y pruebas MUST reflejar 8080 cuando describan el valor predeterminado.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Las pruebas automatizadas relacionadas con configuración y despliegue pasan con el puerto predeterminado 8080.
- **SC-002**: Una búsqueda de referencias operativas a 8420 no devuelve valores predeterminados activos del API.

## Assumptions

- El cambio afecta únicamente al puerto predeterminado; los usuarios pueden seguir seleccionando otro puerto mediante `DTC_API_PORT` o `--port`.
- No se cambia la interfaz de red ni las rutas HTTP.
