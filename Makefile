# Optional shortcuts; on the VM `docker compose up -d` is all that is needed.
COMPOSE   := docker compose
TOOLS     := $(COMPOSE) run --rm -T tools
CFG       := --config user_data/config.json
# Keep DATA_FROM in sync with agent/run_loop.sh.
DATA_FROM := 20250801
STRATEGY  ?= $(shell python3 -c 'import json;print(json.load(open("user_data/config.strategy.json"))["strategy"])')

.PHONY: help build env chat-id watchlist data test cov backtest lock up down logs soak loop

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

build: ## Build the tools image (freqtrade + pytest + Claude Code)
	$(COMPOSE) build research

env: ## Create or complete .env, generating the API secrets (never prints values)
	python3 scripts/init_env.py

chat-id: ## Store TELEGRAM_CHAT_ID in .env (message the bot first, bot must be stopped)
	python3 scripts/telegram_chat_id.py

watchlist: ## Rebuild the 15-pair watchlist from Binance 24h volume
	$(TOOLS) python scripts/build_watchlist.py

data: ## Download or refresh 1h/2h/4h futures candles for the watchlist
	$(TOOLS) freqtrade download-data $(CFG) --timerange $(DATA_FROM)- --timeframes 1h 2h 4h

test: ## Run the test suite
	$(TOOLS) pytest

cov: ## Run tests with coverage for guardrails, strategies and the agent tooling
	$(TOOLS) pytest --cov=user_data/strategies --cov=agent --cov=dashboard --cov-report=term-missing

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

loop: ## Run one research loop now (in the research container)
	$(COMPOSE) run --rm research agent/run_loop.sh
