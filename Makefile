.DEFAULT_GOAL := help
COMPOSE := docker compose --env-file backend/.env --env-file frontend/.env
DEV_USER ?= alice
MESSAGE ?= Hello from Make
export CHAT_USER := $(DEV_USER)
export CHAT_MESSAGE := $(MESSAGE)

.PHONY: help env build start stop logs status migrate seed test backend-test frontend-test frontend-build chat history health login logout

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "%-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

env: ## Initialize separate backend/frontend local env files
	@python3 scripts/env.py

build: env ## Build backend and frontend images
	$(COMPOSE) build backend frontend

start: build ## Build, migrate, seed, and start the local application
	$(COMPOSE) up -d --wait db
	$(MAKE) migrate
	$(MAKE) seed
	$(COMPOSE) up -d --wait backend frontend

migrate: env ## Apply Alembic migrations explicitly
	$(COMPOSE) run --rm --no-deps backend alembic upgrade head

seed: env ## Create Alice and Bob (safe to repeat)
	$(COMPOSE) run --rm --no-deps backend python -m chatbot.adapters.outbound.postgres.seed

stop: ## Stop services; preserve PostgreSQL data
	$(COMPOSE) down

logs: ## Follow application logs
	$(COMPOSE) logs -f backend frontend

status: ## Show service status
	$(COMPOSE) ps

test: backend-test frontend-test frontend-build ## Run backend/frontend tests and the checked production build

backend-test: ## Run backend tests using isolated DBs in the existing PostgreSQL
	$(COMPOSE) exec -T backend pytest -q

frontend-test: ## Run focused frontend tests
	$(COMPOSE) exec -T frontend npm test

frontend-build: ## Typecheck and compile the static frontend
	$(COMPOSE) exec -T frontend npm run build

login: ## Interactive CLI login; saves a private ignored cookie jar
	@python3 scripts/chat.py login

logout: ## Revoke the current CLI session and remove its cookie jar
	@python3 scripts/chat.py logout

chat: ## Stream a message using your CLI session (or explicit development mode)
	@python3 scripts/chat.py chat

history: ## Read saved history using your CLI session
	@python3 scripts/chat.py history

health: ## Check readiness
	$(COMPOSE) exec -T backend python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/health/ready").read().decode())'
