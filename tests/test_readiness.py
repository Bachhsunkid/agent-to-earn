import json
import subprocess
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

import common
import readiness
from dashboard import app as dash

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
START = NOW - timedelta(days=20)
UPTIME = {"uptime": 0.99, "hours": 72.0, "errors": 0}
CONFIG = {"strategy": "TrendRegimeV1", "dry_run": True}


def api_trade(hours: float, pair="BTC/USDT:USDT", short=False, profit=1.0, strategy="TrendRegimeV1", is_open=False):
    opened = START + timedelta(hours=hours)
    return {"pair": pair, "is_short": short, "open_date": opened.strftime("%Y-%m-%d %H:%M:%S"),
            "profit_abs": profit, "strategy": strategy, "is_open": is_open}


def bt_trade(hours: float, pair="BTC/USDT:USDT", short=False, profit=1.0):
    return readiness.normalize({"pair": pair, "is_short": short, "profit_abs": profit,
                                "open_date": (START + timedelta(hours=hours)).isoformat()})


def test_match_pairs_by_pair_side_and_nearest_entry():
    paper = [bt_trade(0), bt_trade(10, short=True), bt_trade(50, pair="ETH/USDT:USDT")]
    backtest = [bt_trade(1.5), bt_trade(0.5), bt_trade(10), bt_trade(53, pair="ETH/USDT:USDT")]
    assert readiness.match(paper, backtest) == {"matched": 1, "paper_only": 2, "backtest_only": 3,
                                                "agreement": pytest.approx(2 / 7)}
    assert readiness.match([], [])["agreement"] is None


def evaluate(trades, backtest, uptime=UPTIME, config=CONFIG):
    return readiness.evaluate(config, trades, lambda strategy, start, end: backtest, uptime, NOW)


def test_ready_when_paper_matches_backtest_long_enough():
    trades = [api_trade(h * 20) for h in range(22)] + [api_trade(5, strategy="OldStrategy"), api_trade(6, is_open=True)]
    report = evaluate(trades, [bt_trade(h * 20 + 0.5) for h in range(22)])
    assert report["verdict"] == "ready", report["checks"]
    assert report["comparison"] == {"matched": 22, "paper_only": 0, "backtest_only": 0, "agreement": 1.0,
                                    "paper_trades": 22, "backtest_trades": 22, "paper_profit": 22.0,
                                    "backtest_profit": 22.0}


def test_wait_for_more_days_and_trades():
    report = evaluate([api_trade(470)], [bt_trade(470)])
    statuses = {c["name"]: c["status"] for c in report["checks"]}
    assert report["verdict"] == "wait" and statuses["paper_days"] == "wait" and statuses["sample"] == "wait"
    assert evaluate([], [])["comparison"] is None


def test_paper_days_start_at_the_first_entry_even_if_still_open():
    report = evaluate([api_trade(0, is_open=True), api_trade(-48, strategy="OldStrategy")], [])
    days = next(c for c in report["checks"] if c["name"] == "paper_days")
    assert days["detail"].startswith("20.0 of 14 days") and days["status"] == "pass"
    assert report["verdict"] == "wait" and report["comparison"] is None


def test_small_sample_misses_wait_instead_of_failing():
    report = evaluate([api_trade(470, profit=-1)], [])
    statuses = {c["name"]: c["status"] for c in report["checks"]}
    assert report["verdict"] == "wait"
    assert statuses["agreement"] == statuses["profitable"] == "wait" and statuses["profit_vs_backtest"] == "pass"


@pytest.mark.parametrize("trades, backtest, uptime, failed", [
    ([api_trade(h * 20) for h in range(22)], [bt_trade(h * 20 + 5) for h in range(22)], UPTIME, "agreement"),
    ([api_trade(h * 20, profit=0.2) for h in range(22)], [bt_trade(h * 20) for h in range(22)], UPTIME,
     "profit_vs_backtest"),
    ([api_trade(h * 20, profit=-1) for h in range(22)], [bt_trade(h * 20, profit=-1) for h in range(22)], UPTIME,
     "profitable"),
    ([api_trade(h * 20) for h in range(22)], [bt_trade(h * 20) for h in range(22)],
     {"uptime": 0.5, "hours": 72.0, "errors": 3}, "uptime"),
])
def test_not_ready(trades, backtest, uptime, failed):
    report = evaluate(trades, backtest, uptime)
    assert report["verdict"] == "not_ready"
    assert [c["name"] for c in report["checks"] if c["status"] == "fail"] == [failed]


def test_live_mode_is_flagged():
    report = evaluate([], [], config={"strategy": "S", "dry_run": False})
    assert report["checks"][0] == {"name": "mode", "status": "info",
                                   "detail": "bot is trading live; readiness applies to paper trading"}


def test_paper_trades_pages_through_the_api():
    pages = {0: {"trades": [{"n": i} for i in range(500)]}, 500: {"trades": [{"n": 500}]}}

    def get(path):
        if path == "show_config":
            return CONFIG
        if path == "status":
            return [{"n": "open"}]
        return pages[int(path.split("offset=")[1])]

    config, trades = readiness.paper_trades(get)
    assert config == CONFIG and len(trades) == 502 and trades[0] == {"n": "open"}


def test_backtest_trades_runs_freqtrade_and_filters_window(tmp_path, monkeypatch):
    import freqtrade.data.btanalysis as bta

    monkeypatch.setattr(common, "RESULTS", tmp_path)
    calls = []
    monkeypatch.setattr(common, "run_tools", lambda args: calls.append(args) or subprocess.CompletedProcess(args, 0, "", ""))
    frame = pd.DataFrame([
        # Paper fills seconds after the candle: the backtest entry on that candle still counts.
        {"pair": "ETH/USDT:USDT", "is_short": False, "profit_abs": 1.0, "exit_reason": "roi",
         "open_date": pd.Timestamp(START - timedelta(seconds=10))},
        {"pair": "BTC/USDT:USDT", "is_short": False, "profit_abs": 2.0, "exit_reason": "roi",
         "open_date": pd.Timestamp(START + timedelta(hours=1))},
        {"pair": "BTC/USDT:USDT", "is_short": True, "profit_abs": 9.0, "exit_reason": "roi",
         "open_date": pd.Timestamp(START - timedelta(hours=3))},
        {"pair": "SOL/USDT:USDT", "is_short": True, "profit_abs": 4.0, "exit_reason": "force_exit",
         "open_date": pd.Timestamp(START + timedelta(hours=5))},
    ])
    monkeypatch.setattr(bta, "load_backtest_data", lambda directory, strategy: frame)
    trades = readiness.backtest_trades("TrendRegimeV1", START, NOW)
    assert trades == [{"pair": "ETH/USDT:USDT", "short": False, "open": START - timedelta(seconds=10), "profit": 1.0},
                      {"pair": "BTC/USDT:USDT", "short": False, "open": START + timedelta(hours=1), "profit": 2.0}]
    assert calls[0][1] == "download-data" and calls[1][1] == "backtesting"
    assert "20261030-20261121" in calls[1]

    monkeypatch.setattr(common, "run_tools", lambda args: subprocess.CompletedProcess(args, 2, "", "no data"))
    with pytest.raises(RuntimeError, match="download-data failed"):
        readiness.backtest_trades("TrendRegimeV1", START, NOW)


def test_main_writes_report_and_reports_errors(tmp_path, monkeypatch, capsys):
    log = tmp_path / "freqtrade.log"
    log.write_text("")
    monkeypatch.setattr(readiness.soak, "LOG", log)
    monkeypatch.setattr(readiness, "paper_trades", lambda: (CONFIG, []))
    out = tmp_path / "readiness" / "latest.json"
    assert readiness.main(["--write", str(out)]) == 1  # no heartbeats: uptime fails
    report = json.loads(out.read_text())
    assert report["verdict"] == "not_ready" and json.loads(capsys.readouterr().out) == report
    assert [p.name for p in out.parent.iterdir()] == ["latest.json"]

    monkeypatch.setattr(readiness, "paper_trades", lambda: (_ for _ in ()).throw(OSError("bot down")))
    assert readiness.main([]) == 1
    assert json.loads(capsys.readouterr().out)["checks"][0]["detail"] == "OSError: bot down"


def test_dashboard_shows_readiness(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "RUNS", tmp_path)
    assert dash.readiness_report() is None
    assert "No report yet" in dash.render_readiness(None)
    report = {"verdict": "wait", "strategy": "<S>", "generated_at": "2026-11-20T12:00:00+00:00",
              "checks": [{"name": "sample", "status": "wait", "detail": "3 of 20 closed trades"}]}
    readiness.write(report, tmp_path / "readiness" / "latest.json")
    page = dash.render_readiness(dash.readiness_report())
    assert "keep paper trading" in page and "3 of 20 closed trades" in page and "&lt;S&gt;" in page
