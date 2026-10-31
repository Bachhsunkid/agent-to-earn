"""Season economics from public/site.json: running costs, the profit goal and donations.

The KPI is bot profit >= goal_multiple x running costs. Donations are reported next to it but
never counted as profit: the goal measures whether the bot pays for itself. The public page
does the same arithmetic in public/static/app.js (`economy`); keep the two in sync.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import common

SITE = common.ROOT / "public" / "site.json"
SITE_EXAMPLE = common.ROOT / "public" / "site.example.json"


def load_site(site: Path = SITE, example: Path = SITE_EXAMPLE) -> dict:
    for path in (site, example):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            continue
    return {}


def _date(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def economy(site: dict, profit: float | None, donations_usd: float, now: datetime) -> dict:
    monthly = sum(float(c.get("usd") or 0) for c in site.get("costs_usd_per_month") or [])
    daily_cost = monthly * 12 / 365
    start, end = _date(site.get("started")), _date(site.get("ends"))
    days = max(0.0, (now - start).total_seconds() / 86400) if start else 0.0
    season_days = (end - start).days if start and end else None
    multiple = float(site.get("goal_multiple") or 2)
    profit = profit or 0.0
    spent = daily_cost * days
    goal = spent * multiple
    projected = None
    if season_days and days >= 1:
        # Linear: today's profit rate over the whole season. Crude, but honest about the goal.
        projected = {"profit": profit / days * season_days, "costs": daily_cost * season_days,
                     "goal": daily_cost * season_days * multiple}
    return {"monthly": monthly, "days": days, "season_days": season_days, "multiple": multiple,
            "spent": spent, "goal": goal, "profit": profit, "progress": profit / goal if goal > 0 else None,
            "donations": donations_usd, "donation_cover": donations_usd / spent if spent > 0 else None,
            "net": profit + donations_usd - spent, "projected": projected}
