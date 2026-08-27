# Tasks: Cambiar puerto del API

## Phase 1: Alineación

- [X] T001 [US1] Actualizar referencias operativas y documentación de 8420 a 8080 en README.md, specs/002-config-api/quickstart.md, specs/002-config-api/contracts/http-api.md y specs/003-web-panel/contracts/nginx.md.
- [X] T002 [US1] Actualizar expectativas de puerto predeterminado en tests/test_api_guards.py, tests/test_frontend_guards.py y tests/test_deployment.py.
- [X] T003 [US1] Verificar que src/dynamic_thermal_charge/api/settings.py, deploy/environment.example, deploy/nginx/dynamic-thermal-charge.conf y frontend/proxy.conf.json usan 8080 sin eliminar sobrescrituras explícitas.

## Verification

- [X] T004 Ejecutar la suite focalizada; 71 tests pasan. La guardia de entorno sobre `uvloop` queda excluida porque el paquete ya está instalado globalmente.

## Dependencies

T001-T003 pueden ejecutarse en paralelo; T004 depende de todas.
