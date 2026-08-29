.PHONY: setup dev test lint check build compose-check
setup:
	python3 -m pip install -e 'backend[dev]'
dev:
	python -m dynamic_thermal_charge run --check-config
test:
	python -m pytest backend/tests
lint:
	python -m compileall -q backend/src backend/tests
check: test lint compose-check
build:
	docker build -t dynamic-thermal-charge-backend:local -f backend/Dockerfile backend
	docker build -t dynamic-thermal-charge-frontend:local -f frontend/Dockerfile .
compose-check:
	DOCKERHUB_USERNAME=local APP_VERSION=check docker compose -f deploy/compose.yaml config --quiet
