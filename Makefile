.DEFAULT_GOAL := help
COMPOSE := docker compose
DEV_USER ?= alice
MESSAGE ?= Hello from Make
export CHAT_USER := $(DEV_USER)
export CHAT_MESSAGE := $(MESSAGE)

.PHONY: help env build start stop logs status migrate seed test chat history health

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "%-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

env: ## Create .env from local example if missing
	@test -f .env || cp .env.example .env

build: env ## Build the backend image
	$(COMPOSE) build backend

start: build ## Build, start PostgreSQL, migrate, seed local users, and start the API
	$(COMPOSE) up -d --wait db
	$(MAKE) migrate
	$(MAKE) seed
	$(COMPOSE) up -d --wait backend

migrate: env ## Apply Alembic migrations explicitly
	$(COMPOSE) run --rm --no-deps backend alembic upgrade head

seed: env ## Create Alice and Bob (safe to repeat)
	$(COMPOSE) run --rm --no-deps backend python -m chatbot.adapters.outbound.postgres.seed

stop: ## Stop services; preserve PostgreSQL data
	$(COMPOSE) down

logs: ## Follow backend logs
	$(COMPOSE) logs -f backend

status: ## Show service status
	$(COMPOSE) ps

test: ## Run focused tests in the running backend; use a separate DB in the same PostgreSQL
	$(COMPOSE) exec -T backend pytest -q

chat: ## Stream a message: make chat DEV_USER=bob MESSAGE='Hello'
	$(COMPOSE) exec -T -e CHAT_USER -e CHAT_MESSAGE backend python -c 'import os,json,urllib.request; req=urllib.request.Request("http://127.0.0.1:8080/v1/chat/messages",data=json.dumps({"message":os.environ["CHAT_MESSAGE"]}).encode(),headers={"Content-Type":"application/json","X-Dev-User-Id":os.environ["CHAT_USER"]}); response=urllib.request.urlopen(req); [print(line.decode(),end="",flush=True) for line in response]'

history: ## Read saved history: make history DEV_USER=bob
	$(COMPOSE) exec -T -e CHAT_USER backend python -c 'import os,json,urllib.request; req=urllib.request.Request("http://127.0.0.1:8080/v1/chat/messages",headers={"X-Dev-User-Id":os.environ["CHAT_USER"]}); print(json.dumps(json.load(urllib.request.urlopen(req)),indent=2))'

health: ## Check readiness
	$(COMPOSE) exec -T backend python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/health/ready").read().decode())'
