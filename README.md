# agent-to-earn

Autonomous crypto futures trading on Binance USDⓈ-M with Freqtrade. A nightly Claude Code
research loop proposes new strategies; a deterministic gate decides whether they replace
the live one. Risk rules are fixed in code the agent cannot change. Design and reasoning:
[ADR-0001](docs/adr/0001-guarded-autonomous-trading.md).

Everything runs in Docker containers configured by one `.env` file:

| Service | What it does |
| --- | --- |
| `freqtrade` | The trading bot and FreqUI (`127.0.0.1:8080`). Dry-run unless `DRY_RUN=false`. |
| `dashboard` | Read-only agent activity page (`127.0.0.1:8081`) and the bot watchdog. |
| `research` | Runs the research loop daily at `RESEARCH_AT` (UTC): Claude Code + gate. |
| `public` | Public status page (`127.0.0.1:8082`): no secrets, sanitized snapshot only. |
| `cloudflared` | Publishes the public page through a Cloudflare tunnel (`COMPOSE_PROFILES=public`). |
| `tools` | Same image without secrets, for tests and helper scripts (profile `tools`). |

## Run it (VM or local)

Requirements: Docker with Compose v2, git. Containers run as uid 1000; if your user has a
different uid, run `sudo chown -R 1000:1000 user_data agent` after cloning.

```bash
git clone https://github.com/Bachhsunkid/agent-to-earn.git && cd agent-to-earn
cp .env.example .env    # or `make env`, which also generates the API_* secrets
# fill in .env (see below), then:
docker compose up -d --build
```

`.env` needs:

- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`: a bot from @BotFather and your private chat id
  with it (message the bot, then `make chat-id` while the bot is stopped).
- `API_PASSWORD`, `API_JWT_SECRET` (32+ chars), `API_WS_TOKEN`: long random strings.
- `CLAUDE_CODE_OAUTH_TOKEN`: from `claude setup-token` on any machine logged in to your
  Claude subscription (valid one year). Without it the bot trades but research is skipped.

`docker compose up` refuses to start if a required value is missing. The first research
loop downloads the candle history (a few minutes).

Both pages log in with `API_USERNAME` / `API_PASSWORD`:

- Agent activity: <http://127.0.0.1:8081>: bot state, P&L, open and recent trades,
  research journal, gate decisions (with the held-out numbers), strategy history.
  Read-only, refreshes every minute.
- FreqUI (admin): <http://127.0.0.1:8080>: charts, manual exits, pause/stop.

On the VM keep both ports private: `ssh -L 8080:127.0.0.1:8080 -L 8081:127.0.0.1:8081 <vm>`.

## Public status page

A playful page for everyone else: Bit the mascot (its mood follows the bot), P&L and
trades, the research diary, the strategy graveyard, running costs and donation addresses,
in English and Vietnamese. Design and safety rules: [ADR-0002](docs/adr/0002-public-status-page.md).

- The dashboard writes a whitelisted snapshot to `user_data/public/snapshot.json` every
  minute; the `public` container serves it with `public/static/`. It never publishes
  out-of-sample gate results, logs or errors.
- `cp public/site.example.json public/site.json` and fill in start/end dates, monthly
  costs and donation details (empty entries are hidden). QR images go in
  `public/static/qr/` and are referenced as `qr/<file>.png`. Both are gitignored.
- With `COMPOSE_PROFILES=public` in `.env`, `cloudflared` publishes the page through a
  Cloudflare quick tunnel; `make public-url` prints the URL. It changes when the tunnel
  restarts; switch to a named tunnel once you have a domain.

Telegram is for urgent alerts only: bot down or not RUNNING for 3 minutes (watchdog in the
dashboard container) and recovery, Freqtrade warnings/exceptions, liquidations, emergency
exits, global drawdown breakers, a newly promoted strategy, tampered guardrails, and a
failed or skipped research loop. Everything else is on the dashboard. Freqtrade's Telegram
commands still work: `/status`, `/profit`, `/daily`, `/balance`, `/pause` (stop new
entries), `/forceexit <id|all>`, `/stop`, `/start`.

## Secrets

Each container gets only what it needs: the bot gets Telegram, API and Binance values; the
dashboard and research containers get no Binance keys, and `.env` is masked inside the
research container. The research agent's permissions (`agent/loop.settings.json`) also
deny reading `.env`, `/proc` and the environment. Never commit `.env`.

## Daily operation

The Makefile holds optional shortcuts:

| Command | What it does |
| --- | --- |
| `make logs` | Follow the logs of all services |
| `make public-url` | Print the public page URL (quick tunnel) |
| `make soak` | Stability over the last 24h: heartbeat uptime >= 95%, no errors |
| `make loop` | Run one research loop now (data refresh, Claude, gate) |
| `make backtest STRATEGY=Name` | In-sample backtest (latest 120 days are held out) |
| `make test` / `make cov` | Test suite / with coverage |
| `make watchlist && make data` | Rebuild the 15-pair watchlist by 24h volume |
| `make down` | Stop all services |

The gate promotes strategies on the machine that runs the loop: it changes
`user_data/config.strategy.json` and `user_data/strategies/live/` there, so that checkout is
the source of truth for the live strategy. Commit those changes from it, or expect
conflicts on `git pull`.

## Going live

1. Binance: enable Futures, set Position Mode = One-way and Asset Mode = Single-Asset.
2. Create an API key with **Enable Futures only, withdrawals off**; whitelist the VM IP.
3. In `.env` set `BINANCE_KEY`, `BINANCE_SECRET` and `DRY_RUN=false`, then
   `docker compose up -d`. The bot refuses to start live without the key.
4. Live mode uses `user_data/config.live.json` (`available_capital: 115`, 1/3 of the
   capital) and a separate trade database. Raise the limit once the gate criteria hold live.

## Layout

```
.env.example                       configuration and secrets template
docker-compose.yml                 services; docker/ holds the images and bot entrypoint
user_data/config.json              base config, also used by backtests (operator-owned)
user_data/config.rpc.json          Telegram and REST API settings, running bot only
user_data/config.live.json         live overlay: dry_run off, capital limit
user_data/config.pairs.json        watchlist (scripts/build_watchlist.py)
user_data/config.strategy.json     live strategy name (written by the gate)
user_data/strategies/guarded_strategy.py   risk guardrails
user_data/strategies/live/         the strategy the bot runs
user_data/strategies/candidates/   agent-written candidates
agent/                             research loop, scheduler, gate, backtest wrapper, alerts
dashboard/                         activity page, watchdog, public snapshot writer
public/                            public status page (app, static files, site config)
tests/                             guardrail, strategy, gate, dashboard and tooling tests
```

## Changing guardrails

Protected files are hashed in `agent/guardrails.lock`; the gate refuses to run if they
change. After a deliberate change run `make test && make lock` and commit both.
