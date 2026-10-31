"""Read-only dashboard: what the bot and the research agent are doing.

Runs next to FreqUI on 127.0.0.1:8081 with the same credentials as the Freqtrade API.
It also hosts the watchdog: an urgent Telegram alert when the bot stops answering or
leaves the RUNNING state (Freqtrade cannot report its own death), writes the sanitized
snapshot for the public status page when PUBLIC_SNAPSHOT is set, and tracks donations to the
public wallets when DONATIONS_STATE is set.
"""

import asyncio
import contextlib
import html
import json
import logging
import os
import secrets
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import common
import notify
from dashboard import donations, finance, public_snapshot

logger = logging.getLogger("dashboard")

FREQUI_URL = os.environ.get("FREQUI_URL", "http://127.0.0.1:8080")
WATCHDOG_INTERVAL = int(os.environ.get("WATCHDOG_INTERVAL", "60"))
PUBLIC_SNAPSHOT = os.environ.get("PUBLIC_SNAPSHOT")
DONATIONS_STATE = os.environ.get("DONATIONS_STATE")
DONATIONS_INTERVAL = int(os.environ.get("DONATIONS_INTERVAL", "300"))
JOURNAL = common.ROOT / "agent" / "journal"


# --- data --------------------------------------------------------------------

def bot_get(path: str):
    req = urllib.request.Request(f"{common.BOT_API}/{path}", headers={"Authorization": common.api_auth()})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def bot_status() -> dict:
    try:
        config = bot_get("show_config")
        return {
            "reachable": True,
            "state": config.get("state"),
            "dry_run": config.get("dry_run"),
            "strategy": config.get("strategy"),
            "profit": bot_get("profit"),
            "equity": bot_get("balance").get("total_bot"),
            "open_trades": bot_get("status"),
            # Closed trades, newest first (the API default returns the oldest).
            "recent": bot_get("trades?limit=15&order_by_id=false").get("trades", []),
        }
    except (OSError, KeyError, ValueError) as exc:
        return {"reachable": False, "error": type(exc).__name__}


def _read_json_files(paths) -> list[dict]:
    items = []
    for path in paths:
        try:
            items.append({"file": path.name, **json.loads(path.read_text())})
        except (OSError, ValueError):
            continue
    return items


def gate_reports(limit: int = 20) -> list[dict]:
    gate_dir = common.RUNS / "gate"
    files = sorted((p for p in gate_dir.glob("*.json") if not p.name.startswith("incumbent-")),
                   reverse=True) if gate_dir.exists() else []
    return _read_json_files(files[:limit])


def loop_runs(limit: int = 20) -> list[dict]:
    return _read_json_files(sorted(common.RUNS.glob("loop-*.json"), reverse=True)[:limit])


def journal_entries(limit: int = 14) -> list[dict]:
    entries = []
    for path in sorted(JOURNAL.glob("*.md"), reverse=True)[:limit]:
        section, tldr, notes = None, [], []
        for line in path.read_text().splitlines():
            if line.startswith("## "):
                section = line[3:].strip().lower()
            elif section == "tl;dr" and line.startswith("- "):
                tldr.append(line[2:])
            elif section == "notes" and line.strip():
                notes.append(line)
        entries.append({"date": path.stem, "tldr": tldr, "notes": notes})
    return entries


def readiness_report() -> dict | None:
    try:
        return json.loads((common.RUNS / "readiness" / "latest.json").read_text())
    except (OSError, ValueError):
        return None


def donation_state() -> dict:
    return donations.load_state(Path(DONATIONS_STATE)) if DONATIONS_STATE else donations.empty_state()


def strategies() -> dict:
    def names(directory: Path) -> list[str]:
        return sorted(p.name for p in directory.glob("*.py")) if directory.exists() else []

    try:
        live = common.current_strategy()
    except (OSError, ValueError, KeyError):
        live = "?"
    return {"live": live, "live_files": names(common.LIVE),
            "retired": names(common.ARCHIVE / "retired"), "rejected": names(common.ARCHIVE / "rejected")}


# --- watchdog ------------------------------------------------------------------

class Watchdog:
    """Alert once after `threshold` consecutive unhealthy checks, and once on recovery."""

    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self.failures = 0
        self.alerted = False
        self.last_check: float | None = None
        self.last_problem = ""

    def observe(self, healthy: bool, problem: str = "", now: float | None = None) -> str | None:
        self.last_check = time.time() if now is None else now
        if healthy:
            recovered = self.alerted
            self.failures, self.alerted, self.last_problem = 0, False, ""
            return "Bot recovered: API answering and state RUNNING." if recovered else None
        self.failures += 1
        self.last_problem = problem
        if self.failures >= self.threshold and not self.alerted:
            self.alerted = True
            return f"URGENT: bot unhealthy for {self.failures} checks: {problem}"
        return None


def health_check() -> tuple[bool, str]:
    try:
        state = bot_get("show_config").get("state")
    except (OSError, KeyError, ValueError) as exc:
        return False, f"API unreachable ({type(exc).__name__})"
    return (state == "running"), f"state={state}"


watchdog = Watchdog()


async def watchdog_loop() -> None:
    while True:
        healthy, problem = await asyncio.to_thread(health_check)
        message = watchdog.observe(healthy, problem)
        if message:
            await asyncio.to_thread(notify.send, message)
        await asyncio.sleep(WATCHDOG_INTERVAL)


def write_public_snapshot(path: Path) -> None:
    healthy = None if watchdog.last_check is None else watchdog.failures == 0
    snapshot = public_snapshot.build(bot_get, journal_entries(), loop_runs(limit=400), gate_reports(limit=50),
                                     strategies(), healthy,
                                     donations=donations.ledger(finance.load_site(), donation_state()))
    public_snapshot.write(snapshot, path)


async def snapshot_loop(path: Path) -> None:
    while True:
        try:
            await asyncio.to_thread(write_public_snapshot, path)
        except OSError as exc:
            logger.warning("public snapshot not written: %s", exc)
        await asyncio.sleep(WATCHDOG_INTERVAL)


async def donations_loop(path: Path) -> None:
    while True:
        try:
            errors = await asyncio.to_thread(donations.sync, finance.load_site(), path)
            for error in errors:
                logger.warning("donation sync: %s", error)
        except OSError as exc:
            logger.warning("donation state not written: %s", exc)
        await asyncio.sleep(DONATIONS_INTERVAL)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks = [asyncio.create_task(watchdog_loop())]
    if PUBLIC_SNAPSHOT:
        tasks.append(asyncio.create_task(snapshot_loop(Path(PUBLIC_SNAPSHOT))))
    if DONATIONS_STATE:
        tasks.append(asyncio.create_task(donations_loop(Path(DONATIONS_STATE))))
    yield
    for task in tasks:
        task.cancel()


# --- web -----------------------------------------------------------------------

app = FastAPI(title="agent-to-earn", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
security = HTTPBasic()


def require_auth(credentials: HTTPBasicCredentials = Depends(security)) -> None:
    user, password = os.environ["API_USERNAME"], os.environ["API_PASSWORD"]
    if not (secrets.compare_digest(credentials.username.encode(), user.encode())
            and secrets.compare_digest(credentials.password.encode(), password.encode())):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def pct(value) -> str:
    return "–" if value is None else f"{value:+.1%}" if isinstance(value, (int, float)) else esc(value)


def num(value, digits: int = 2) -> str:
    return "–" if value is None else f"{value:,.{digits}f}" if isinstance(value, (int, float)) else esc(value)


def badge(text: str, kind: str) -> str:
    return f'<span class="badge {kind}">{esc(text)}</span>'


def table(headers: list[str], rows: list[list[str]], empty: str) -> str:
    if not rows:
        return f'<p class="muted">{esc(empty)}</p>'
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def metrics_cell(m: dict | None) -> str:
    if not m:
        return '<span class="muted">–</span>'
    return (f"{num(m.get('total_trades'), 0)} trades · {pct(m.get('profit_total'))} · "
            f"PF {num(m.get('profit_factor'))} · DD {pct(m.get('max_drawdown_account'))}")


def render_bot(bot: dict) -> str:
    if not bot["reachable"]:
        return f'<section><h2>Bot</h2><p>{badge("unreachable", "bad")} {esc(bot["error"])}</p></section>'
    p = bot["profit"]
    state = badge(bot["state"] or "?", "good" if bot["state"] == "running" else "bad")
    mode = badge("dry-run" if bot["dry_run"] else "LIVE", "muted-badge" if bot["dry_run"] else "warn")
    stats = [
        ("Closed P&L", f"{num(p.get('profit_closed_coin'))} USDT ({pct(p.get('profit_closed_ratio'))})"),
        ("Trades", f"{num(p.get('closed_trade_count'), 0)} closed · {len(bot['open_trades'])} open"),
        ("Win / loss", f"{num(p.get('winning_trades'), 0)} / {num(p.get('losing_trades'), 0)}"),
        ("Max drawdown", pct(p.get("max_drawdown"))),
    ]
    tiles = "".join(f'<div class="tile"><div class="label">{esc(k)}</div><div class="value">{v}</div></div>'
                    for k, v in stats)
    open_rows = [[esc(t.get("pair")), "short" if t.get("is_short") else "long", f"{num(t.get('leverage'), 1)}x",
                  num(t.get("stake_amount")), pct(t.get("profit_ratio")), esc(t.get("open_date"))]
                 for t in bot["open_trades"]]
    closed_rows = [[esc(t.get("pair")), "short" if t.get("is_short") else "long", num(t.get("profit_abs")),
                    pct(t.get("profit_ratio")), esc(t.get("exit_reason")), esc(t.get("close_date"))]
                   for t in bot["recent"]]
    return f"""<section><h2>Bot {state} {mode}</h2>
<p class="muted">Strategy <b>{esc(bot['strategy'])}</b> · full control in <a href="{esc(FREQUI_URL)}">FreqUI</a></p>
<div class="tiles">{tiles}</div>
<h3>Open trades</h3>{table(["Pair", "Side", "Lev", "Stake", "Profit", "Opened"], open_rows, "No open trades.")}
<h3>Recently closed</h3>{table(["Pair", "Side", "P&L USDT", "Profit", "Exit", "Closed"], closed_rows, "No closed trades yet.")}
</section>"""


def usd(value) -> str:
    return "–" if value is None else f"{'−' if value < 0 else ''}${abs(value):,.2f}"


def render_finances(site: dict, bot: dict, state: dict, now: datetime) -> str:
    entries = donations.ledger(site, state)
    total = sum(e["usd"] for e in entries if isinstance(e["usd"], (int, float)))
    profit = bot["profit"].get("profit_all_coin") if bot["reachable"] else None
    eco = finance.economy(site, profit, total, now, bot.get("equity"))
    season = f"day {int(eco['days']) + 1} of {eco['season_days']}" if eco["season_days"] else "no season dates in site.json"
    progress = "–" if eco["progress"] is None else f"{eco['progress']:.0%}"
    stats = [
        ("Running costs", f"{usd(eco['monthly'])}/month · {usd(eco['spent'])} so far ({season})"),
        ("Bot P&L (incl. open)", f"{usd(eco['profit'])}" + ("" if bot["reachable"] else " (bot unreachable)")
         + (" · paper" if bot.get("dry_run") else "")),
        (f"KPI: profit ≥ {eco['multiple']:g}× costs", f"{usd(eco['profit'])} of {usd(eco['goal'])} ({progress})"),
        ("Donations (not profit)", f"{usd(total)} from {len(entries)}" + (
            f" · cover {eco['donation_cover']:.0%} of costs" if eco["donation_cover"] is not None else "")),
        ("Net (P&L + donations − costs)", usd(eco["net"])),
    ]
    if eco["needed_return"]:
        need = eco["needed_return"]
        pace = "" if eco["monthly_pace"] is None else f" · pace now {usd(eco['monthly_pace'])}/month"
        stats.append(("Needed per month on equity", f"{need['breakeven']:.1%} to break even, "
                                                    f"{need['goal']:.1%} for the goal{pace}"))
    if eco["projected"]:
        p = eco["projected"]
        verdict = badge("on track", "good") if p["profit"] >= p["goal"] else badge("behind", "warn")
        stats.append(("Season end at this pace", f"{usd(p['profit'])} vs goal {usd(p['goal'])} {verdict}"))
    tiles = "".join(f'<div class="tile"><div class="label">{esc(k)}</div><div class="value">{v}</div></div>'
                    for k, v in stats)
    rows = []
    for e in entries:
        link = donations.explorer_url(e)
        amount = f"{num(e['amount'], 0 if e['currency'] == 'VND' else 2)} {esc(e['currency'])}" if isinstance(e["amount"], (int, float)) else "–"
        rows.append([esc(e["time"][:16].replace("T", " ")), esc(e["via"]), amount, usd(e["usd"]),
                     esc(e["name"] or "–"), f"<code>{esc(e['from'])}</code>" if e["from"] else "manual",
                     f'<a href="{esc(link)}" rel="noopener">tx</a>' if link else esc(e["note"] or "")])
    problems = [badge(err, "bad") for err in state.get("errors", [])]
    problems += [badge(f"gap skipped on {g['wallet']}: blocks {g['from']}–{g['to']} (check the explorer)", "warn")
                 for g in state.get("gaps", [])]
    synced = ", ".join(f"{k.split(':')[0]} {esc(v[11:16])} UTC" for k, v in state.get("synced", {}).items())
    return f"""<section><h2>Finances</h2>
<div class="tiles">{tiles}</div>
<h3>Donations</h3>{table(["Time (UTC)", "Via", "Amount", "USD", "Name", "From", "Tx / note"], rows, "No donations yet.")}
<p class="muted">Last chain sync: {synced or "not yet"}. Momo and internal Binance transfers: add them under
<code>donors.manual</code> in public/site.json; name a wallet under <code>donors.names</code>.</p>
{"<p>" + " ".join(problems) + "</p>" if problems else ""}</section>"""


READINESS_BADGES = {"ready": ("ready to go live", "good"), "wait": ("keep paper trading", "muted-badge"),
                    "not_ready": ("not ready", "bad"), "error": ("check failed", "bad")}
CHECK_BADGES = {"pass": "good", "wait": "muted-badge", "fail": "bad", "info": "muted-badge"}


def render_readiness(report: dict | None) -> str:
    if not report:
        return ('<section><h2>Go-live readiness</h2><p class="muted">No report yet. It runs before each '
                'research loop; <code>make readiness</code> runs it now.</p></section>')
    text, kind = READINESS_BADGES.get(report.get("verdict"), (report.get("verdict"), "bad"))
    rows = [[badge(c["status"], CHECK_BADGES.get(c["status"], "bad")), esc(c["name"]), esc(c["detail"])]
            for c in report.get("checks", [])]
    return f"""<section><h2>Go-live readiness {badge(text, kind)}</h2>
<p class="muted">Paper trading of <b>{esc(report.get("strategy") or "?")}</b> compared with its backtest over the
same days · {esc(report.get("generated_at", "")[:16].replace("T", " "))} UTC · going live stays your decision
(README, "Going live").</p>
{table(["", "Check", "Detail"], rows, "No checks.")}</section>"""


def render_research(journal: list[dict], runs: list[dict]) -> str:
    run_by_date = {}
    for run in runs:
        run_by_date.setdefault(run.get("date"), run)
    items = []
    for entry in journal:
        run = run_by_date.get(entry["date"])
        kind = {"done": "good", "running": "muted-badge"}.get(run["stage"], "bad") if run else ""
        run_badge = badge(run["stage"], kind) if run else ""
        tldr = "".join(f"<li>{esc(line)}</li>" for line in entry["tldr"]) or "<li class='muted'>no TL;DR</li>"
        notes = esc("\n".join(entry["notes"]))
        items.append(f"""<article><h3>{esc(entry['date'])} {run_badge}</h3><ul>{tldr}</ul>
<details><summary>Notes</summary><pre>{notes}</pre></details></article>""")
    failed_runs = [r for r in runs if r.get("stage") not in ("done", "running")]
    failures = "".join(f"<li>{esc(r.get('stamp'))}: failed at {esc(r.get('stage'))}</li>" for r in failed_runs)
    return (f"<section><h2>Research loop</h2>{''.join(items) or '<p class=muted>No research runs yet.</p>'}"
            f"{f'<h3>Failed runs</h3><ul>{failures}</ul>' if failures else ''}</section>")


def failed_checks(checks: dict) -> str:
    # Criteria checks list short names; the others carry long logs, kept in the JSON report.
    return "; ".join(f"{k}: {', '.join(v)}" if k in ("in_sample", "out_of_sample") else k
                     for k, v in checks.items() if v != "ok") or "–"


def render_gate(reports: list[dict]) -> str:
    rows = []
    for r in reports:
        result = badge("passed" if r.get("passed") else "failed", "good" if r.get("passed") else "bad")
        rows.append([esc(r.get("time", "")[:16].replace("T", " ")), esc(r.get("strategy") or r.get("candidate")),
                     result, esc(r.get("action", "–")), esc(failed_checks(r.get("checks", {}))),
                     metrics_cell(r.get("in_sample")), metrics_cell(r.get("out_of_sample_private"))])
    return ("<section><h2>Gate decisions</h2>" + table(
        ["Time (UTC)", "Strategy", "Result", "Action", "Failed checks", "In-sample", "Out-of-sample"],
        rows, "No gate runs yet.") + "</section>")


def render_strategies(s: dict) -> str:
    def chips(names):
        return " ".join(f'<code>{esc(n)}</code>' for n in names) or '<span class="muted">none</span>'

    return f"""<section><h2>Strategies</h2><dl>
<dt>Live</dt><dd><b>{esc(s['live'])}</b> {chips(s['live_files'])}</dd>
<dt>Retired</dt><dd>{chips(s['retired'])}</dd>
<dt>Rejected</dt><dd>{chips(s['rejected'])}</dd></dl></section>"""


def render_watchdog(w: Watchdog) -> str:
    if w.last_check is None:
        return badge("watchdog starting", "muted-badge")
    checked = datetime.fromtimestamp(w.last_check, UTC).strftime("%H:%M:%S UTC")
    if w.failures:
        return badge(f"watchdog: {w.failures} failed checks ({w.last_problem})", "bad") + f" {checked}"
    return badge("watchdog ok", "good") + f' <span class="muted">{checked}</span>'


STYLE = """
:root{--bg:#f7f7f5;--card:#fff;--text:#1d1d1b;--muted:#6b6b66;--line:#e4e4df;--good:#1f7a4d;--bad:#b3261e;--warn:#9a6700;--accent:#2f5bd3}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--text:#ecece8;--muted:#9a9a93;--line:#33332f;--good:#5cc28f;--bad:#f2867c;--warn:#e0b44c;--accent:#8aa8ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}header{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline;justify-content:space-between}
h1{font-size:20px;margin:8px 0}h2{font-size:17px;margin:0 0 8px}h3{font-size:15px;margin:16px 0 6px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}
a{color:var(--accent)}.muted{color:var(--muted)}code{font-size:13px;background:var(--bg);padding:1px 6px;border-radius:4px}
.badge{display:inline-block;font-size:12px;font-weight:600;padding:1px 8px;border-radius:999px;border:1px solid currentColor;vertical-align:middle}
.good{color:var(--good)}.bad{color:var(--bad)}.warn{color:var(--warn)}.muted-badge{color:var(--muted)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:8px}
.tile{border:1px solid var(--line);border-radius:8px;padding:8px 12px}.label{font-size:12px;color:var(--muted)}.value{font-weight:600}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600}article{border-top:1px solid var(--line);padding-top:4px}article:first-of-type{border-top:0}
pre{white-space:pre-wrap;font-size:13px;margin:4px 0}dl{display:grid;grid-template-columns:max-content 1fr;gap:6px 12px;margin:0}dt{color:var(--muted)}dd{margin:0}
"""


def render_page() -> str:
    moment = datetime.now(UTC)
    now = moment.strftime("%Y-%m-%d %H:%M UTC")
    bot = bot_status()
    body = "".join([
        render_bot(bot),
        render_finances(finance.load_site(), bot, donation_state(), moment),
        render_readiness(readiness_report()),
        render_research(journal_entries(), loop_runs()),
        render_gate(gate_reports()),
        render_strategies(strategies()),
    ])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60">
<title>Agent Activity</title><style>{STYLE}</style></head>
<body><main><header><h1>agent-to-earn</h1><div>{render_watchdog(watchdog)} <span class="muted">· {now} · refreshes every minute</span></div></header>
{body}</main></body></html>"""


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def index() -> str:
    return render_page()
