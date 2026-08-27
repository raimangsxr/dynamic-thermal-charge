# Implementation Plan: Cambiar puerto del API

**Branch**: `006-api-port` | **Date**: 2026-08-28 | **Spec**: [spec.md](spec.md)

## Summary

Actualizar el puerto predeterminado del API de 8420 a 8080 y alinear proxies, despliegue, documentación y pruebas, manteniendo las sobrescrituras explícitas.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: FastAPI, uvicorn, Angular dev proxy, nginx
**Storage**: N/A
**Testing**: pytest
**Target Platform**: Linux/Raspberry Pi y desarrollo local
**Project Type**: CLI y servicio web
**Performance Goals**: Sin cambio
**Constraints**: Mantener `DTC_API_PORT` y `--port` compatibles
**Scale/Scope**: Un valor predeterminado y sus referencias operativas

## Constitution Check

GATE: PASS. El cambio tiene especificación, plan, tareas y verificación; no altera dominio, persistencia ni seguridad.

## Project Structure

```text
src/dynamic_thermal_charge/api/settings.py
src/dynamic_thermal_charge/cli.py
deploy/
frontend/proxy.conf.json
tests/
README.md
specs/006-api-port/
```

**Structure Decision**: Mantener la estructura existente y cambiar únicamente las referencias al puerto predeterminado.

## Complexity Tracking

N/A.
