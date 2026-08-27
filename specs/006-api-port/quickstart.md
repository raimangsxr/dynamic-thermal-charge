# Quickstart

1. Ejecutar `pytest -q tests/test_api_guards.py tests/test_deployment.py tests/test_frontend_guards.py`.
2. Verificar que la configuración predeterminada devuelve `8080`.
3. Verificar que `DTC_API_PORT=9000` y `--port 9000` siguen sobrescribiendo el valor.
