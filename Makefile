# The five contract targets -- setup, dev, test, lint, check -- come from the
# AI Engineering Standard harness, which runs both components: pytest and ruff
# for the backend, vitest and the production build for the panel. See
# .ai-standard/project.mk for what is wired to what.
include .ai-standard/make/entry.mk

.PHONY: build compose-check

build:
	docker build -t dynamic-thermal-charge-backend:local -f backend/Dockerfile backend
	docker build -t dynamic-thermal-charge-frontend:local -f frontend/Dockerfile .

compose-check:
	DOCKERHUB_USERNAME=local APP_VERSION=check docker compose -f deploy/compose.yaml config --quiet
	docker compose -f deploy/compose.dev.yaml config --quiet
	docker compose -f deploy/compose.dev.yaml -f deploy/compose.dev-postgres.yaml config --quiet
