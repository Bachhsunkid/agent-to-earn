import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import common
import notify
from dashboard import app as dash

AUTH = ("admin", "pw")
JOURNAL = """# 2026-10-29 research loop

## TL;DR
- Hypothesis: <script>alert(1)</script>
- Gate: failed (out_of_sample: beat_live_profit)

## Notes
- Next: try 4h.
"""
BOT = {
    "show_config": {"state": "running", "dry_run": True, "strategy": "TrendRegimeV1"},
    "profit": {"profit_closed_coin": 12.5, "profit_closed_ratio": 0.0368, "closed_trade_count": 4,
               "winning_trades": 3, "losing_trades": 1, "max_drawdown": 0.02},
    "balance": {"total_bot": 340.0},
    "status": [{"pair": "BTC/USDT:USDT", "is_short": True, "leverage": 6.7, "stake_amount": 17,
                "profit_ratio": 0.012, "open_date": "2026-10-29 16:00:00"}],
    "trades?limit=15&order_by_id=false": {"trades": [
        {"pair": "ZEC/USDT:USDT", "is_short": False, "profit_abs": 4.1, "profit_ratio": 0.2,
         "exit_reason": "exit_signal", "close_date": "2026-10-29 15:00:00"}]},
}


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.setenv("API_USERNAME", AUTH[0])
    monkeypatch.setenv("API_PASSWORD", AUTH[1])
    strategy_config = tmp_path / "config.strategy.json"
    strategy_config.write_text(json.dumps({"strategy": "TrendRegimeV1"}))
    for name, path in {"STRATEGY_CONFIG": strategy_config, "RUNS": tmp_path / "runs",
                       "LIVE": tmp_path / "live", "ARCHIVE": tmp_path / "archive"}.items():
        monkeypatch.setattr(common, name, path)
    monkeypatch.setattr(dash, "JOURNAL", tmp_path / "journal")
    monkeypatch.setattr(dash, "watchdog", dash.Watchdog())
    for d in ("runs/gate", "live", "archive/rejected", "journal"):
        (tmp_path / d).mkdir(parents=True)
    return tmp_path


def fake_bot(monkeypatch, replies=BOT):
    def get(path):
        if replies is None:
            raise OSError("down")
        return replies[path]
    monkeypatch.setattr(dash, "bot_get", get)


def test_bot_status(tree, monkeypatch):
    fake_bot(monkeypatch)
    status = dash.bot_status()
    assert status["reachable"] and status["state"] == "running" and status["equity"] == 340.0
    assert status["recent"][0]["pair"] == "ZEC/USDT:USDT"
    fake_bot(monkeypatch, None)
    assert dash.bot_status() == {"reachable": False, "error": "OSError"}


def test_bot_get_uses_basic_auth(tree, monkeypatch):
    seen = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            return b'{"status": "pong"}'

    monkeypatch.setattr(dash.urllib.request, "urlopen", lambda req, timeout: seen.append(req) or Resp())
    assert dash.bot_get("ping") == {"status": "pong"}
    assert seen[0].full_url.endswith("/api/v1/ping") and seen[0].get_header("Authorization").startswith("Basic ")


def test_files(tree):
    (tree / "journal" / "2026-10-29.md").write_text(JOURNAL)
    (tree / "runs" / "loop-20261029T010000Z.json").write_text(json.dumps({"date": "2026-10-29", "stage": "done"}))
    (tree / "runs" / "loop-20261028T010000Z.json").write_text("{broken")
    gate_dir = tree / "runs" / "gate"
    (gate_dir / "20261029T020000Z-X.json").write_text(json.dumps({"strategy": "X", "passed": False}))
    (gate_dir / "incumbent-TrendRegimeV1-20260701.json").write_text("{}")
    (tree / "live" / "trend_regime_v1.py").write_text("")
    (tree / "archive" / "rejected" / "x.py").write_text("")

    entry = dash.journal_entries()[0]
    assert entry["date"] == "2026-10-29" and len(entry["tldr"]) == 2 and entry["notes"] == ["- Next: try 4h."]
    assert [r["stage"] for r in dash.loop_runs()] == ["done"]  # broken record skipped
    assert [r["strategy"] for r in dash.gate_reports()] == ["X"]  # incumbent cache skipped
    assert dash.strategies() == {"live": "TrendRegimeV1", "live_files": ["trend_regime_v1.py"],
                                 "retired": [], "rejected": ["x.py"]}
    common.STRATEGY_CONFIG.unlink()
    assert dash.strategies()["live"] == "?"


def test_failed_checks():
    assert dash.failed_checks({"integrity": "ok", "static": "ok"}) == "–"
    assert dash.failed_checks({"tests": ["long log"], "out_of_sample": ["min_profit", "beat_live_profit"]}) == (
        "tests; out_of_sample: min_profit, beat_live_profit")


def test_watchdog_alerts_once_and_on_recovery():
    w = dash.Watchdog(threshold=3)
    assert w.observe(True) is None
    assert [w.observe(False, "state=stopped", now=1.0) for _ in range(2)] == [None, None]
    assert w.observe(False, "state=stopped").startswith("URGENT: bot unhealthy for 3 checks: state=stopped")
    assert w.observe(False, "state=stopped") is None  # no repeat
    assert w.observe(True).startswith("Bot recovered")
    assert w.observe(True) is None


def test_health_check(monkeypatch):
    monkeypatch.setattr(dash, "bot_get", lambda path: {"state": "running"})
    assert dash.health_check() == (True, "state=running")
    monkeypatch.setattr(dash, "bot_get", lambda path: {"state": "stopped"})
    assert dash.health_check() == (False, "state=stopped")
    fake_bot(monkeypatch, None)
    assert dash.health_check() == (False, "API unreachable (OSError)")


def test_watchdog_loop_sends_alert(tree, monkeypatch):
    monkeypatch.setattr(dash, "watchdog", dash.Watchdog(threshold=1))
    monkeypatch.setattr(dash, "health_check", lambda: (False, "API unreachable (OSError)"))
    sent = []
    monkeypatch.setattr(notify, "send", lambda text: sent.append(text) or True)

    async def stop(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(dash.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(dash.watchdog_loop())
    assert sent == ["URGENT: bot unhealthy for 1 checks: API unreachable (OSError)"]


def test_page_requires_auth(tree, monkeypatch):
    fake_bot(monkeypatch)
    client = TestClient(dash.app)
    assert client.get("/").status_code == 401
    assert client.get("/", auth=("admin", "wrong")).status_code == 401
    assert client.get("/docs").status_code == 404


def test_page_renders(tree, monkeypatch):
    fake_bot(monkeypatch)
    (tree / "journal" / "2026-10-29.md").write_text(JOURNAL)
    (tree / "runs" / "loop-20261029T010000Z.json").write_text(json.dumps({"stamp": "s", "date": "2026-10-29",
                                                                        "stage": "done", "exit": 0}))
    (tree / "runs" / "loop-20261028T010000Z.json").write_text(json.dumps({"stamp": "old", "date": "2026-10-28",
                                                                        "stage": "claude", "exit": 1}))
    (tree / "runs" / "gate" / "20261029T020000Z-X.json").write_text(json.dumps({
        "strategy": "X", "time": "2026-10-29T02:00:00+00:00", "passed": False, "action": "rejected",
        "checks": {"integrity": "ok", "out_of_sample": ["beat_live_profit"]},
        "in_sample": {"total_trades": 50, "profit_total": 0.45, "profit_factor": 1.23, "max_drawdown_account": 0.22},
        "out_of_sample_private": {"total_trades": 20, "profit_total": -0.02, "profit_factor": 0.9,
                                  "max_drawdown_account": 0.1}}))
    page = TestClient(dash.app).get("/", auth=AUTH)
    assert page.status_code == 200
    text = page.text
    assert "&lt;script&gt;" in text and "<script>alert" not in text
    assert "BTC/USDT:USDT" in text and "6.7x" in text and "ZEC/USDT:USDT" in text
    assert "out_of_sample: beat_live_profit" in text and "PF 1.23" in text and "-2.0%" in text
    assert "failed at claude" in text and "watchdog starting" in text


def test_page_when_bot_down_and_empty(tree, monkeypatch):
    fake_bot(monkeypatch, None)
    dash.watchdog.observe(False, "API unreachable (OSError)", now=0.0)
    text = TestClient(dash.app).get("/", auth=AUTH).text
    assert "unreachable" in text and "No research runs yet." in text and "No gate runs yet." in text
    assert "watchdog: 1 failed checks" in text
    dash.watchdog.observe(True, now=0.0)
    assert "watchdog ok" in dash.render_watchdog(dash.watchdog)


def test_formatters():
    assert dash.pct(None) == "–" and dash.pct(0.1) == "+10.0%" and dash.pct("x") == "x"
    assert dash.num(None) == "–" and dash.num(1234.5) == "1,234.50" and dash.num("<b>") == "&lt;b&gt;"
    assert dash.metrics_cell(None).endswith("–</span>")


def test_lifespan_starts_and_stops_watchdog(tree, monkeypatch):
    monkeypatch.setattr(dash, "health_check", lambda: (True, "state=running"))
    fake_bot(monkeypatch)
    with TestClient(dash.app) as client:
        assert client.get("/", auth=AUTH).status_code == 200
