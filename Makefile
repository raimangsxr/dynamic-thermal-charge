.PHONY: setup dev test lint check build compose-check
setup:
	python3 -m pip install -e '.[dev]'
dev:
	python -m dynamic_thermal_charge run --check-config
test:
	python -m pytest
lint:
	python -m compileall -q src tests
check: test lint compose-check
build:
	docker build -t dynamic-thermal-charge-backend:local -f backend/Dockerfile .
	docker build -t dynamic-thermal-charge-frontend:local -f frontend/Dockerfile .
compose-check:
	DOCKERHUB_USERNAME=local APP_VERSION=check docker compose -f deploy/compose.yaml config --quiet
