"""Sanitized snapshot for the public status page (public/).

The dashboard writes it every minute to a file the `public` container serves. Only the
fields listed here leave the private side. Out-of-sample gate numbers never do: the research
agent has network access and must not learn the held-out results from the public page.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

VERSION = 1
CRITERIA_CHECKS = ("in_sample", "out_of_sample")


def _trade_side(t: dict) -> str:
    return "short" if t.get("is_short") else "long"


def open_trade(t: dict) -> dict:
    return {"pair": t.get("pair"), "side": _trade_side(t), "leverage": t.get("leverage"),
            "stake_usdt": t.get("stake_amount"), "profit_pct": t.get("profit_ratio"),
            "profit_usdt": t.get("profit_abs"), "opened_at": t.get("open_date")}


def closed_trade(t: dict) -> dict:
    return {"pair": t.get("pair"), "side": _trade_side(t), "profit_usdt": t.get("profit_abs"),
            "profit_pct": t.get("profit_ratio"), "exit_reason": t.get("exit_reason"),
            "opened_at": t.get("open_date"), "closed_at": t.get("close_date")}


def profit_summary(p: dict) -> dict:
    return {"closed_usdt": p.get("profit_closed_coin"), "closed_pct": p.get("profit_closed_ratio"),
            "total_usdt": p.get("profit_all_coin"), "trades": p.get("closed_trade_count"),
            "wins": p.get("winning_trades"), "losses": p.get("losing_trades"), "winrate": p.get("winrate"),
            "profit_factor": p.get("profit_factor"), "max_drawdown": p.get("max_drawdown"),
            "current_drawdown": p.get("current_drawdown"),
            "bot_started_at": p.get("bot_start_date"), "first_trade_at": p.get("first_trade_date")}


def bot_section(bot_get) -> dict:
    try:
        config = bot_get("show_config")
        bot = {
            "online": True,
            "state": config.get("state"),
            "paper": bool(config.get("dry_run", True)),
            "strategy": config.get("strategy"),
            "profit": profit_summary(bot_get("profit")),
            "open": [open_trade(t) for t in bot_get("status")],
            "closed": [closed_trade(t) for t in bot_get("trades?limit=30&order_by_id=false").get("trades", [])],
            "daily": [{"date": d.get("date"), "profit_usdt": d.get("abs_profit"), "trades": d.get("trade_count"),
                       "balance_usdt": d.get("starting_balance")}
                      for d in bot_get("daily?timescale=60").get("data", [])],
        }
    except (OSError, KeyError, ValueError, AttributeError, TypeError):
        # Never publish the error itself: it can carry hostnames or response bodies.
        return {"online": False}
    return bot


def failed_checks(checks: dict) -> list[str]:
    """Names only; criteria checks list short criterion names, the others carry logs."""
    failed = []
    for name, value in checks.items():
        if value == "ok":
            continue
        if name in CRITERIA_CHECKS and isinstance(value, list):
            failed += [f"{name}.{c}" for c in value]
        else:
            failed.append(name)
    return failed


def in_sample(m: dict | None) -> dict | None:
    if not m:
        return None
    return {"trades": m.get("total_trades"), "profit_pct": m.get("profit_total"),
            "profit_factor": m.get("profit_factor"), "max_drawdown": m.get("max_drawdown_account")}


def gate_entry(r: dict) -> dict:
    return {"time": r.get("time"), "strategy": r.get("strategy") or r.get("candidate"),
            "passed": bool(r.get("passed")), "promoted": str(r.get("action", "")).startswith("promoted"),
            "failed": failed_checks(r.get("checks", {})), "in_sample": in_sample(r.get("in_sample"))}


def research_section(journal: list[dict], runs: list[dict]) -> dict:
    stage_by_date = {}
    for run in runs:
        stage_by_date.setdefault(run.get("date"), run.get("stage"))
    return {
        "running": bool(runs) and runs[0].get("stage") == "running",
        "runs": {"total": len(runs), "done": sum(r.get("stage") == "done" for r in runs)},
        "diary": [{"date": e["date"], "stage": stage_by_date.get(e["date"]), "tldr": e["tldr"],
                   "notes": "\n".join(e["notes"])[:3000]} for e in journal],
    }


def mood(bot: dict, research: dict, today: str) -> str:
    """One word the page turns into a face and a speech bubble."""
    if not bot.get("online") or bot.get("state") != "running":
        return "down"
    if research["running"]:
        return "researching"
    open_profit = sum(t.get("profit_usdt") or 0 for t in bot["open"])
    if bot["open"]:
        return "winning" if open_profit >= 0 else "nervous"
    today_profit = sum(d.get("profit_usdt") or 0 for d in bot["daily"] if d.get("date") == today)
    if today_profit > 0:
        return "happy"
    if today_profit < 0:
        return "sad"
    return "idle"


def build(bot_get, journal: list[dict], runs: list[dict], gates: list[dict], strategies: dict,
          watchdog_ok: bool | None, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    bot = bot_section(bot_get)
    research = research_section(journal, runs)
    return {
        "version": VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "mood": mood(bot, research, now.strftime("%Y-%m-%d")),
        "bot": bot,
        "research": research,
        # Reports without an action are gate dry runs (promote_on_pass=False), not decisions.
        "gate": [gate_entry(r) for r in gates if r.get("action")],
        "strategies": {"live": strategies.get("live"), "retired": strategies.get("retired", [])},
        "watchdog_ok": watchdog_ok,
    }


def write(snapshot: dict, path: Path) -> None:
    """Atomic replace, so the public service never reads half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, separators=(",", ":"), default=str))
    os.replace(tmp, path)
