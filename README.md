# agent-to-earn

Autonomous crypto futures trading on Binance USDⓈ-M with Freqtrade. A nightly Claude Code
research loop proposes new strategies; a deterministic gate decides whether they replace
the live one. Risk rules are fixed in code the agent cannot change. Design and reasoning:
[ADR-0001](docs/adr/0001-guarded-autonomous-trading.md).

Everything runs in Docker containers configured by one `.env` file:

| Service | What it does |
| --- | --- |
| `freqtrade` | The trading bot and FreqUI (`127.0.0.1:8080`). Dry-run unless `DRY_RUN=false`. |
| `dashboard` | Read-only agent activity and finances page (`127.0.0.1:8081`), the bot watchdog, donation tracking. |
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

`docker compose up` refuses to start if a required value is missing. The bot only enters
pairs on the day's universe list ([ADR-0006](docs/adr/0006-point-in-time-universe.md)), so
build it once before the first night, then fetch the candles (about half an hour):

```bash
make universe && make data && docker compose restart freqtrade
```

The nightly research loop rebuilds the universe and refreshes the candles after that.

Both pages log in with `API_USERNAME` / `API_PASSWORD`:

- Agent activity: <http://127.0.0.1:8081>: bot state, P&L, open and recent trades,
  research journal, gate decisions (with the held-out numbers), strategy history.
  Read-only, refreshes every minute.
- FreqUI (admin): <http://127.0.0.1:8080>: charts, manual exits, pause/stop.

On the VM keep both ports private: `ssh -L 8080:127.0.0.1:8080 -L 8081:127.0.0.1:8081 <vm>`.

## Continuous deployment

`.github/workflows/ci.yml` runs the tests on every push and pull request; pushes to `main`
that pass are deployed to the VM over SSH with a key that can only run the deploy script.
Design and safety rules: [ADR-0003](docs/adr/0003-github-actions-deploy.md).

One-time setup, as root on the VM from the repo root:

```bash
sh scripts/setup_deploy_user.sh <vm public IP> <ssh port>
```

It creates the restricted `deploy` user and prints four values. Add them as repository
secrets (Settings > Secrets and variables > Actions): `VM_HOST`, `VM_PORT`, `VM_SSH_KEY`,
`VM_KNOWN_HOSTS`. Until they exist the deploy step is skipped. Re-run the script after
changing `scripts/vm_deploy.sh` (it installs a root-owned copy; `--new-key` rotates the key).

A deploy refuses to run, and the job fails with the reason, when the research loop is
running or the VM checkout has uncommitted changes to tracked files (a gate promotion:
commit it from the VM first). It restarts only the services whose mounted code changed.

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
- Donations: the dashboard scans the USDT wallets listed under `donate.crypto` (each with a
  `network`: `bsc`, `eth` or `tron`) every 5 minutes through public nodes, no API keys, and
  keeps what it finds in `user_data/finance/`. Momo and internal Binance transfers never
  reach a chain: add them under `donors.manual`, e.g. `{"date": "2026-11-01", "via": "Momo",
  "amount": 50000, "currency": "VND", "name": "An", "note": "Go Bit!"}` (VND uses `vnd_per_usd`). `donors.names` maps a wallet or tx to the
  name shown in the Hall of Fame (otherwise a shortened wallet). Donations are shown next
  to the KPI, never counted as profit. Design: [ADR-0004](docs/adr/0004-donation-tracking.md).
- The dashboard's Finances section has the season ledger: running costs, bot P&L, the
  profit ≥ 2× costs KPI with a linear projection, donations and net.
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
| `make readiness` | Go-live check: paper trades vs backtest, sample size, uptime |
| `make loop` | Run one research loop now (data refresh, Claude, gate) |
| `make backtest STRATEGY=Name` | In-sample backtest (latest 120 days are held out) |
| `make test` / `make cov` | Test suite / with coverage |
| `make universe && make data` | Rebuild today's top-15 volume universe and fetch its candles |
| `make down` | Stop all services |

The gate promotes strategies on the machine that runs the loop: it changes
`user_data/config.strategy.json` and `user_data/strategies/live/` there, so that checkout is
the source of truth for the live strategy. Commit those changes from it, or expect
conflicts on `git pull`.

## Going live

Wait for the dashboard's **Go-live readiness** section to say *ready to go live*
([ADR-0005](docs/adr/0005-go-live-readiness.md)): at least 14 days and 20 closed paper trades,
at least 70% of them matching the backtest of the same days, paper P&L positive and not far
below the backtest, and 95% uptime. It runs before every research loop; `make readiness`
runs it now. Then:

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
user_data/universe.json            daily top-15 volume lists (scripts/build_universe.py)
user_data/config.pairs.json        whitelist: every pair ever in the universe (generated)
user_data/config.strategy.json     live strategy name (written by the gate)
user_data/strategies/guarded_strategy.py   risk guardrails
user_data/strategies/live/         the strategy the bot runs
user_data/strategies/candidates/   agent-written candidates
agent/                             research loop, scheduler, gate, backtest wrapper, alerts
dashboard/                         activity page, watchdog, public snapshot writer
public/                            public status page (app, static files, site config)
tests/                             guardrail, strategy, gate, dashboard and tooling tests
.github/workflows/ci.yml           tests, then deploy to the VM (scripts/vm_deploy.sh)
```

## Changing guardrails

Protected files are hashed in `agent/guardrails.lock`; the gate refuses to run if they
change. After a deliberate change run `make test && make lock` and commit both.
