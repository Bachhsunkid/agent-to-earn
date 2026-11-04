# Optional shortcuts; on the VM `docker compose up -d` is all that is needed.
COMPOSE   := docker compose
TOOLS     := $(COMPOSE) run --rm -T tools
CFG       := --config user_data/config.json
# Keep DATA_FROM in sync with agent/run_loop.sh.
DATA_FROM := 20250801
STRATEGY  ?= $(shell python3 -c 'import json;print(json.load(open("user_data/config.strategy.json"))["strategy"])')

.PHONY: help build env chat-id universe data test cov backtest lock up down logs soak readiness loop public-url

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

build: ## Build the tools image (freqtrade + pytest + Claude Code)
	$(COMPOSE) build research

env: ## Create or complete .env, generating the API secrets (never prints values)
	python3 scripts/init_env.py

chat-id: ## Store TELEGRAM_CHAT_ID in .env (message the bot first, bot must be stopped)
	python3 scripts/telegram_chat_id.py

universe: ## Rebuild the point-in-time top-15 volume universe and its whitelist (also nightly)
	$(TOOLS) python scripts/build_universe.py

data: ## Download or refresh 1h/2h/4h futures candles for the whitelist
	$(TOOLS) freqtrade download-data $(CFG) --timerange $(DATA_FROM)- --timeframes 1h 2h 4h

test: ## Run the test suite
	$(TOOLS) pytest

cov: ## Run tests with coverage for guardrails, strategies and the agent tooling
	$(TOOLS) pytest --cov=user_data/strategies --cov=agent --cov=dashboard --cov=public --cov-report=term-missing

backtest: ## Backtest a strategy in-sample (STRATEGY=Name, default: live)
	$(TOOLS) python agent/bt.py $(STRATEGY)

lock: ## Re-hash protected guardrail files after a deliberate change
	python3 scripts/lock_guardrails.py

up: ## Start bot, dashboard and research loop (DRY_RUN in .env picks paper or live)
	$(COMPOSE) up -d --build

down: ## Stop all services
	$(COMPOSE) down

logs: ## Follow the logs of all services
	$(COMPOSE) logs -f --tail 100

soak: ## Stability over the last 24h: heartbeat uptime >= 95% and no errors
	python3 scripts/soak_check.py

readiness: ## Go-live check: paper trades vs backtest, sample size, uptime (also runs nightly)
	$(COMPOSE) run --rm -T research python3 agent/readiness.py --write agent/runs/readiness/latest.json

loop: ## Run one research loop now (in the research container)
	$(COMPOSE) run --rm research agent/run_loop.sh

public-url: ## Print the public page URL (Cloudflare quick tunnel; changes on restart)
	@$(COMPOSE) logs cloudflared | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1
