COMPOSE_PROD := docker compose -f compose.yaml
COMPOSE_DEV := $(COMPOSE_PROD) -f compose-dev.yaml
RUN := $(COMPOSE_DEV) run --rm app

.DEFAULT_GOAL := help

.PHONY: help dev-build dev-run dev-shell dev-psql prod-build prod-run worker-shell redis-cli db-upgrade db-downgrade db-migrate db-history format lint lint-fix type-check css-build test test-cov

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev-build: ## Build the dev container image
	$(COMPOSE_DEV) build

dev-run: ## Run the app in foreground (http://localhost:5009)
	$(COMPOSE_DEV) up

prod-build: ## Build the prod image (no dev overlay)
	$(COMPOSE_PROD) build

prod-run: ## Run the prod stack in foreground (gunicorn, no mounts)
	$(COMPOSE_PROD) up

dev-shell: ## Open a bash shell inside the app container
	$(RUN) bash

worker-shell: ## Open a bash shell inside the worker container
	$(COMPOSE_DEV) run --rm worker bash

redis-cli: ## Open redis-cli against the dev Redis
	$(COMPOSE_DEV) exec redis redis-cli

dev-psql: ## Open psql against the dev Postgres
	$(COMPOSE_DEV) exec postgres psql -U struudel -d struudel

db-upgrade: ## Apply all pending migrations
	$(RUN) alembic upgrade head

db-downgrade: ## Rollback one migration
	$(RUN) alembic downgrade -1

db-migrate: ## Generate migration – MSG="description" required
	$(RUN) alembic revision --autogenerate -m "$(MSG)"

db-history: ## Show migration history
	$(RUN) alembic history

format: ## Format code with ruff
	$(RUN) ruff format .

lint: ## Lint code with ruff
	$(RUN) ruff check .

lint-fix: ## Lint and auto-fix with ruff
	$(RUN) ruff check --fix .

type-check: ## Type-check with ty
	$(RUN) ty check

test: ## Run pytest test-suite
	$(RUN) pytest

test-cov: ## Run pytest with coverage report
	$(RUN) pytest --cov=struudel --cov-report=term-missing

css-build: ## Build Tailwind + daisyUI CSS (one-shot, minified)
	$(RUN) tailwindcss -i /app/css/input.css -o /app/src/struudel/static/css/app.css --minify
