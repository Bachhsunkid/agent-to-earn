import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from dashboard import app as dash
from dashboard import public_snapshot as ps
from public import app as pub

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
SECRET_OOS = 0.4242  # out-of-sample number that must never be published
BOT = {
    "show_config": {"state": "running", "dry_run": True, "strategy": "TrendRegimeV1",
                    "exchange": {"key": "binance-key"}},
    "profit": {"profit_closed_coin": 12.5, "profit_closed_ratio": 0.0368, "profit_all_coin": 13.0,
               "closed_trade_count": 4, "winning_trades": 3, "losing_trades": 1, "winrate": 0.75,
               "profit_factor": 1.8, "max_drawdown": 0.02, "current_drawdown": 0.01, "bot_start_date": "2026-10-31 08:00:00"},
    "status": [{"pair": "BTC/USDT:USDT", "is_short": True, "leverage": 6.7, "stake_amount": 17,
                "profit_ratio": 0.012, "profit_abs": 0.2, "open_date": "2026-10-31 10:00:00", "orders": ["x"]}],
    "trades?limit=30&order_by_id=false": {"trades": [
        {"pair": "ZEC/USDT:USDT", "is_short": False, "profit_abs": 4.1, "profit_ratio": 0.2,
         "exit_reason": "exit_signal", "open_date": "2026-10-30 01:00:00", "close_date": "2026-10-30 15:00:00",
         "orders": ["y"]}]},
    "daily?timescale=60": {"data": [{"date": "2026-10-31", "abs_profit": 4.1, "trade_count": 1,
                                     "starting_balance": 336.6, "rel_profit": 0.01}]},
}
GATES = [
    {"strategy": "WideStopTrendV3", "time": "2026-10-31T03:59:15+00:00", "passed": False, "action": "rejected",
     "checks": {"integrity": "ok", "tests": ["Traceback /workspace/secret/path"],
                "out_of_sample": ["beat_live_profit"]},
     "in_sample": {"total_trades": 50, "profit_total": 0.36, "profit_factor": 1.17, "max_drawdown_account": 0.22},
     "out_of_sample_private": {"total_trades": 20, "profit_total": SECRET_OOS, "profit_factor": 0.9}},
    {"strategy": "TrendRegimeV2", "time": "2026-10-30T03:00:00+00:00", "passed": True,
     "action": "promoted; bot reloaded", "checks": {}},
    {"strategy": "GateSmokeTest", "passed": False, "checks": {}},  # dry run, no action
]
JOURNAL = [{"date": "2026-10-31", "tldr": ["Hypothesis: wider stops"], "notes": ["- try 4h"]}]
RUNS = [{"date": "2026-10-31", "stage": "done"}]
STRATEGIES = {"live": "TrendRegimeV1", "live_files": ["trend_regime_v1.py"], "retired": [], "rejected": ["x.py"]}


def fake_get(replies=BOT):
    def get(path):
        if replies is None:
            raise OSError("connection refused to http://freqtrade:8080 with user admin")
        return replies[path]
    return get


def build(**kw):
    args = {"bot_get": fake_get(), "journal": JOURNAL, "runs": RUNS, "gates": GATES,
            "strategies": STRATEGIES, "watchdog_ok": True, "now": NOW} | kw
    return ps.build(**args)


def test_snapshot_publishes_only_whitelisted_fields():
    snap = build()
    text = json.dumps(snap)
    for leaked in ("out_of_sample_private", str(SECRET_OOS), "binance-key", "Traceback", "orders", "x.py"):
        assert leaked not in text
    bot = snap["bot"]
    assert bot["online"] and bot["paper"] and bot["strategy"] == "TrendRegimeV1"
    assert bot["open"] == [{"pair": "BTC/USDT:USDT", "side": "short", "leverage": 6.7, "stake_usdt": 17,
                            "profit_pct": 0.012, "profit_usdt": 0.2, "opened_at": "2026-10-31 10:00:00"}]
    assert bot["closed"][0]["side"] == "long" and bot["profit"]["total_usdt"] == 13.0
    assert bot["profit"]["current_drawdown"] == 0.01
    assert bot["daily"] == [{"date": "2026-10-31", "profit_usdt": 4.1, "trades": 1, "balance_usdt": 336.6}]
    assert [g["strategy"] for g in snap["gate"]] == ["WideStopTrendV3", "TrendRegimeV2"]
    assert snap["gate"][0]["failed"] == ["tests", "out_of_sample.beat_live_profit"]
    assert snap["gate"][0]["in_sample"] == {"trades": 50, "profit_pct": 0.36, "profit_factor": 1.17,
                                            "max_drawdown": 0.22}
    assert snap["gate"][1]["promoted"] and snap["gate"][1]["in_sample"] is None
    assert snap["research"]["diary"] == [{"date": "2026-10-31", "stage": "done",
                                          "tldr": ["Hypothesis: wider stops"], "notes": "- try 4h"}]
    assert snap["strategies"] == {"live": "TrendRegimeV1", "retired": []}
    assert snap["generated_at"] == "2026-10-31T12:00:00+00:00" and snap["watchdog_ok"] is True


def test_bot_down_hides_the_error():
    snap = build(bot_get=fake_get(None))
    assert snap["bot"] == {"online": False} and snap["mood"] == "down"
    assert "freqtrade" not in json.dumps(snap)


@pytest.mark.parametrize("change, expected", [
    ({"show_config": {**BOT["show_config"], "state": "stopped"}}, "down"),
    ({}, "winning"),
    ({"status": [{**BOT["status"][0], "profit_abs": -1.0}]}, "nervous"),
    ({"status": []}, "happy"),
    ({"status": [], "daily?timescale=60": {"data": [{"date": "2026-10-31", "abs_profit": -2}]}}, "sad"),
    ({"status": [], "daily?timescale=60": {"data": [{"date": "2026-10-30", "abs_profit": 5}]}}, "idle"),
])
def test_mood(change, expected):
    assert build(bot_get=fake_get(BOT | change))["mood"] == expected


def test_mood_researching_while_loop_runs():
    assert build(runs=[{"date": "2026-10-31", "stage": "running"}])["mood"] == "researching"


def test_write_is_atomic(tmp_path):
    target = tmp_path / "public" / "snapshot.json"
    ps.write(build(), target)
    assert json.loads(target.read_text())["version"] == ps.VERSION
    assert [p.name for p in target.parent.iterdir()] == ["snapshot.json"]


def test_dashboard_snapshot_loop_writes_file(tmp_path, monkeypatch):
    target = tmp_path / "snapshot.json"
    for name, value in {"bot_get": fake_get(), "journal_entries": lambda: JOURNAL, "loop_runs": lambda limit: RUNS,
                        "gate_reports": lambda limit: GATES, "strategies": lambda: STRATEGIES}.items():
        monkeypatch.setattr(dash, name, value)
    monkeypatch.setattr(dash, "watchdog", dash.Watchdog())

    async def stop(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(dash.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(dash.snapshot_loop(target))
    snap = json.loads(target.read_text())
    assert snap["bot"]["strategy"] == "TrendRegimeV1" and snap["watchdog_ok"] is None

    monkeypatch.setattr(dash, "write_public_snapshot", lambda path: (_ for _ in ()).throw(OSError("read-only")))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(dash.snapshot_loop(target))  # a write error is logged, the loop keeps going


def test_dashboard_lifespan_starts_snapshot_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("API_USERNAME", "admin")
    monkeypatch.setenv("API_PASSWORD", "pw")
    monkeypatch.setattr(dash, "PUBLIC_SNAPSHOT", str(tmp_path / "snapshot.json"))
    monkeypatch.setattr(dash, "health_check", lambda: (True, "state=running"))
    started = []

    async def fake_loop(path):
        started.append(path)

    monkeypatch.setattr(dash, "snapshot_loop", fake_loop)
    with TestClient(dash.app):
        pass
    assert started == [tmp_path / "snapshot.json"]


@pytest.fixture
def public_client(tmp_path, monkeypatch):
    monkeypatch.setattr(pub, "SNAPSHOT", tmp_path / "snapshot.json")
    monkeypatch.setattr(pub, "SITE", tmp_path / "site.json")
    return TestClient(pub.app), tmp_path


def test_public_app_serves_page_and_snapshot(public_client):
    client, tmp = public_client
    page = client.get("/")
    assert page.status_code == 200 and "Bit the Trading Bot" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    script = client.get("/app.js")
    assert script.status_code == 200 and page.headers["cache-control"] == script.headers["cache-control"] == "no-cache"
    assert client.get("/app.js", headers={"If-None-Match": script.headers["etag"]}).status_code == 304

    missing = client.get("/api/snapshot.json")
    assert missing.status_code == 503 and missing.headers["cache-control"] == "no-store"
    ps.write(build(), tmp / "snapshot.json")
    assert client.get("/api/snapshot.json").json()["bot"]["strategy"] == "TrendRegimeV1"

    assert client.get("/api/site.json").json()["goal_multiple"] == 2  # falls back to the example
    (tmp / "site.json").write_text(json.dumps({"goal_multiple": 3}))
    assert client.get("/api/site.json").json() == {"goal_multiple": 3}
    for path in ("/docs", "/openapi.json", "/../app.py", "/site.example.json"):
        assert client.get(path).status_code == 404


def test_compose_isolates_the_public_page():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    for name in ("public", "cloudflared"):
        service = services[name]
        assert service["networks"] == ["edge"]
        assert all(not k.startswith(("API_", "TELEGRAM", "FREQTRADE", "BINANCE", "CLAUDE"))
                   for k in service.get("environment", {}))
    assert services["public"]["volumes"] == ["./public:/srv/public:ro", "./user_data/public:/data:ro"]
    assert "networks" not in services["freqtrade"] and "networks" not in services["dashboard"]
    assert services["cloudflared"]["image"] != "cloudflare/cloudflared:latest"
