# The five contract targets -- setup, dev, test, lint, check -- come from the
# AI Engineering Standard harness, which runs both components: pytest and ruff
# for the backend, vitest and the production build for the panel. See
# .ai-standard/project.mk for what is wired to what.
include .ai-standard/make/entry.mk

.PHONY: build delivery-check compose-check compose-dev compose-dev-postgres compose-down compose-down-postgres compose-clean compose-clean-postgres

# Development Compose resources are scoped to the absolute checkout path. An
# explicit COMPOSE_PROJECT_NAME remains available for CI or scripted runs.
# The PostgreSQL matrix reuses COMPOSE_DEV so both variants share one identity.
COMPOSE_PROJECT_NAME ?= $(shell python3 deploy/compose_project_name.py)
COMPOSE_DEV = docker compose --project-name "$(COMPOSE_PROJECT_NAME)" -f deploy/compose.dev.yaml
COMPOSE_DEV_POSTGRES = $(COMPOSE_DEV) -f deploy/compose.dev-postgres.yaml

build:
	docker build -t dynamic-thermal-charge-backend:local -f backend/Dockerfile backend
	docker build -t dynamic-thermal-charge-frontend:local -f frontend/Dockerfile .

delivery-check:
	python3 deploy/check_delivery.py

compose-check:
	DOCKERHUB_USERNAME=local APP_VERSION=check DTC_GPIO_GID=986 docker compose -f deploy/compose.yaml config --quiet
	$(COMPOSE_DEV) config --quiet
	$(COMPOSE_DEV_POSTGRES) config --quiet

compose-dev:
	$(COMPOSE_DEV) up -d --build --wait

compose-dev-postgres:
	$(COMPOSE_DEV_POSTGRES) up -d --build --wait

compose-down:
	$(COMPOSE_DEV) down --remove-orphans

compose-down-postgres:
	$(COMPOSE_DEV_POSTGRES) down --remove-orphans

compose-clean:
	$(COMPOSE_DEV) down --remove-orphans --volumes

compose-clean-postgres:
	$(COMPOSE_DEV_POSTGRES) down --remove-orphans --volumes
