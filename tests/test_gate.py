import io
import json
import subprocess
import urllib.error
from datetime import date
from pathlib import Path

import pytest

import bt
import bt_metrics
import common
import gate
import notify

GUARDED = gate.guarded_members()

GOOD = '''"""A valid candidate."""
import talib.abstract as ta
from pandas import DataFrame
from guarded_strategy import GuardedStrategy

WINDOW = 20
LABEL: str = "x"


class GoodCandidate(GuardedStrategy):
    timeframe = "1h"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema"] = ta.EMA(dataframe, timeperiod=WINDOW)
        self.cache = 1
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        return dataframe
'''

METHOD_ANCHOR = "    def populate_entry_trend"


def check(source, taken=()):
    return gate.static_check(source, set(taken), GUARDED)


def with_method_body(line: str) -> str:
    return GOOD.replace(METHOD_ANCHOR, f"    def extra(self):\n        {line}\n\n{METHOD_ANCHOR}")


# --- static checks -------------------------------------------------------------

def test_good_candidate_passes():
    assert check(GOOD) == ("GoodCandidate", [])


def test_guarded_members_parsed_from_guard():
    assert {"leverage", "custom_stake_amount", "stoploss", "protections"} <= GUARDED


def test_guarded_members_missing_raises():
    with pytest.raises(ValueError):
        gate.guarded_members("X = 1\n")


@pytest.mark.parametrize("snippet, expected", [
    ("import os", "import not allowed: os"),
    ("from freqtrade.persistence import Trade", "import not allowed: freqtrade.persistence"),
    ("from . import helper", "import not allowed: ."),
    ("print('hi')", "top-level statement not allowed"),
    ("GuardedStrategy.leverage = None", "attribute assignment outside self"),
    ("def helper():\n    return 1", "top-level statement not allowed"),
])
def test_module_level_violations(snippet, expected):
    _, errors = check(GOOD + "\n" + snippet + "\n")
    assert any(expected in e for e in errors), errors


@pytest.mark.parametrize("line, expected", [
    ("return eval('1')", "forbidden name: eval"),
    ("return open('/etc/passwd')", "forbidden name: open"),
    ("return self.__class__", "dunder attribute access: __class__"),
    ("global WINDOW", "global/nonlocal not allowed"),
    ("import math", "imports must be at module level"),
    ("pd.options = None", "attribute assignment outside self"),
    ("a.b, c = 1, 2", "attribute assignment outside self"),
])
def test_method_body_violations(line, expected):
    _, errors = check(with_method_body(line))
    assert any(expected in e for e in errors), errors


@pytest.mark.parametrize("member", ["    stoploss = -0.9", "    stoploss: float = -0.9",
                                    "    def leverage(self, *args, **kwargs):\n        return 50"])
def test_overriding_guarded_member_rejected(member):
    _, errors = check(GOOD.replace('    timeframe = "1h"', f'    timeframe = "1h"\n{member}'))
    assert any("overrides guarded member" in e for e in errors), errors


def test_class_shape_violations():
    _, errors = check(GOOD.replace("(GuardedStrategy)", "(GuardedStrategy, object)"))
    assert any("must inherit only" in e for e in errors)
    _, errors = check(GOOD.replace("class GoodCandidate", "@dataclass\nclass GoodCandidate"))
    assert any("class decorators" in e for e in errors)
    _, errors = check(GOOD.replace("class GoodCandidate", "class bad"))
    assert any("invalid class name" in e for e in errors)
    name, errors = check(GOOD + "\n\nclass Other(GuardedStrategy):\n    pass\n")
    assert name is None and any("exactly one class" in e for e in errors)


def test_taken_class_name_rejected():
    _, errors = check(GOOD, taken={"GoodCandidate"})
    assert errors == ["class name already used: GoodCandidate"]


def test_syntax_error():
    name, errors = check("class (:")
    assert name is None and errors[0].startswith("syntax error")


def test_class_names(tmp_path):
    (tmp_path / "a.py").write_text("class A: pass\nclass B: pass\n")
    (tmp_path / "broken.py").write_text("class (:")
    assert gate.class_names([tmp_path / "a.py", tmp_path / "broken.py", tmp_path / "nope.py"]) == {"A", "B"}


# --- integrity -----------------------------------------------------------------

@pytest.fixture
def protected_tree(tmp_path, monkeypatch):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text(name)
    monkeypatch.setattr(gate, "PROTECTED", ["a.txt", "b.txt"])
    return tmp_path


def test_integrity_ok_then_detects_change(protected_tree):
    lock = protected_tree / "lock.json"
    gate.write_lock(lock, protected_tree)
    assert gate.check_integrity(lock, protected_tree) == []
    (protected_tree / "a.txt").write_text("tampered")
    assert gate.check_integrity(lock, protected_tree) == ["protected file changed: a.txt"]
    (protected_tree / "b.txt").unlink()
    assert "protected file changed: b.txt" in gate.check_integrity(lock, protected_tree)


def test_integrity_missing_lock_and_unlocked_file(protected_tree, monkeypatch):
    lock = protected_tree / "lock.json"
    assert gate.check_integrity(lock, protected_tree) == ["guardrails.lock missing (run: make lock)"]
    gate.write_lock(lock, protected_tree)
    monkeypatch.setattr(gate, "PROTECTED", ["a.txt", "b.txt", "c.txt"])
    assert gate.check_integrity(lock, protected_tree) == ["protected file not locked: c.txt"]


def test_repo_lock_matches_protected_files():
    assert gate.check_integrity() == []


# --- criteria ------------------------------------------------------------------

GOOD_OOS = {"total_trades": 30, "profit_factor": 1.3, "profit_total": 0.2, "profit_total_abs": 68,
            "max_drawdown_account": 0.1, "max_leverage": 10.0}


def test_evaluate_passes_and_fails_each_rule():
    rules = gate.CRITERIA["out_of_sample"]
    assert gate.evaluate(GOOD_OOS, rules) == []
    bad = {"total_trades": 1, "profit_factor": 0.5, "profit_total": -0.1,
           "max_drawdown_account": 0.5, "max_leverage": 20}
    assert gate.evaluate(bad, rules) == ["min_trades", "min_profit_factor", "min_profit",
                                         "max_drawdown", "max_leverage"]
    assert gate.evaluate({}, gate.CRITERIA["in_sample"]) == ["min_trades", "min_profit_factor"]


def test_beats_incumbent():
    assert gate.beats_incumbent(GOOD_OOS, None) == []
    assert gate.beats_incumbent(GOOD_OOS, {"profit_total_abs": 10, "max_drawdown_account": 0.08}) == []
    assert gate.beats_incumbent(GOOD_OOS, {"profit_total_abs": 100, "max_drawdown_account": 0.01}) == [
        "beat_live_profit", "beat_live_drawdown"]


# --- dynamic checks with docker mocked ------------------------------------------

def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_run_tests(monkeypatch):
    monkeypatch.setattr(common, "run_tools", lambda args, **kw: completed(0))
    assert gate.run_tests() == []
    monkeypatch.setattr(common, "run_tools", lambda args, **kw: completed(1, "1 failed"))
    assert gate.run_tests()[0].startswith("test suite failed")


@pytest.mark.parametrize("csv_rows, expected", [
    ("Cand,False", []),
    ("Cand,True", ["lookahead bias detected"]),
    ("Other,False", ["lookahead-analysis produced no result"]),
])
def test_lookahead(tmp_path, monkeypatch, csv_rows, expected):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    out = tmp_path / "user_data/backtest_results/gate/lookahead-Cand.csv"

    def fake_run(args, **kw):
        out.write_text("filename,strategy,has_bias\n" + "f.py," + csv_rows + "\n")
        return completed(0)

    monkeypatch.setattr(common, "run_tools", fake_run)
    errors = gate.lookahead("Cand", "20250815-20260701")
    assert len(errors) == len(expected) and all(e.startswith(x) for e, x in zip(errors, expected))


def test_lookahead_command_failure(monkeypatch):
    monkeypatch.setattr(common, "run_tools", lambda args, **kw: completed(2, "", "boom"))
    assert gate.lookahead("Cand", "x")[0].startswith("lookahead-analysis failed")


def test_incumbent_oos_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "GATE_RESULTS", tmp_path)
    calls = []
    monkeypatch.setattr(common, "backtest", lambda s, t, tag: calls.append(s) or {"profit_total_abs": 5})
    assert gate.incumbent_oos("Live", "20260701-") == {"profit_total_abs": 5}
    assert gate.incumbent_oos("Live", "20260701-") == {"profit_total_abs": 5}
    assert calls == ["Live"]


def test_incumbent_oos_backtest_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "GATE_RESULTS", tmp_path)

    def fail(*args):
        raise RuntimeError("x")

    monkeypatch.setattr(common, "backtest", fail)
    assert gate.incumbent_oos("Live", "20260701-") is None


# --- promotion -----------------------------------------------------------------

@pytest.fixture
def strategy_tree(tmp_path, monkeypatch):
    live, cands, archive = tmp_path / "live", tmp_path / "candidates", tmp_path / "archive"
    for d in (live, cands):
        d.mkdir()
    (live / "old.py").write_text("class OldLive: pass\n")
    (cands / "good.py").write_text(GOOD)
    cfg = tmp_path / "config.strategy.json"
    cfg.write_text(json.dumps({"strategy": "OldLive"}))
    for attr, value in {"LIVE": live, "CANDIDATES": cands, "ARCHIVE": archive,
                        "STRATEGY_CONFIG": cfg, "RUNS": tmp_path / "runs"}.items():
        monkeypatch.setattr(common, attr, value)
    monkeypatch.setattr(gate, "GATE_RESULTS", tmp_path / "runs" / "gate")
    monkeypatch.setattr(gate, "RUN_LOCK", tmp_path / "runs" / ".gate.lock")
    return tmp_path


def test_promote_and_reject(strategy_tree):
    gate.promote(strategy_tree / "candidates" / "good.py", "GoodCandidate")
    assert (strategy_tree / "live" / "good.py").exists()
    assert (strategy_tree / "archive" / "retired" / "old.py").exists()
    assert json.loads((strategy_tree / "config.strategy.json").read_text()) == {"strategy": "GoodCandidate"}
    (strategy_tree / "candidates" / "bad.py").write_text("x")
    gate.reject(strategy_tree / "candidates" / "bad.py")
    assert (strategy_tree / "archive" / "rejected" / "bad.py").exists()


def fake_dynamic(monkeypatch, oos_metrics=GOOD_OOS, integrity=()):
    monkeypatch.setattr(gate, "check_integrity", lambda: list(integrity))
    monkeypatch.setattr(gate, "run_tests", lambda: [])
    monkeypatch.setattr(gate, "lookahead", lambda s, t: [])
    monkeypatch.setattr(gate, "incumbent_oos", lambda s, t: {"profit_total_abs": 1, "max_drawdown_account": 0.1})
    monkeypatch.setattr(gate, "reload_bot", lambda: "bot reloaded")
    in_sample = {"total_trades": 100, "profit_factor": 1.2, "profit_total": 0.3,
                 "max_drawdown_account": 0.2, "max_leverage": 10.0}
    monkeypatch.setattr(common, "backtest",
                        lambda s, t, tag: oos_metrics if t.endswith("-") else in_sample)


def test_run_gate_promotes_passing_candidate(strategy_tree, monkeypatch):
    fake_dynamic(monkeypatch)
    report = gate.run_gate(strategy_tree / "candidates" / "good.py", date(2026, 10, 29))
    assert report["passed"] and report["action"] == "promoted; bot reloaded"
    assert (strategy_tree / "live" / "good.py").exists()
    assert "out_of_sample_private" not in gate.public_view(report)
    assert gate.summary_text(report).startswith("Gate PASSED: GoodCandidate")


def test_run_gate_rejects_on_oos_failure_without_leaking_numbers(strategy_tree, monkeypatch):
    fake_dynamic(monkeypatch, oos_metrics={**GOOD_OOS, "max_drawdown_account": 0.5})
    report = gate.run_gate(strategy_tree / "candidates" / "good.py", date(2026, 10, 29))
    assert not report["passed"] and report["action"] == "rejected"
    assert report["checks"]["out_of_sample"] == ["max_drawdown", "beat_live_drawdown"]
    assert (strategy_tree / "archive" / "rejected" / "good.py").exists()
    text = gate.summary_text(report)
    assert "out_of_sample: max_drawdown" in text and "0.5" not in text


def test_run_gate_stops_at_integrity_failure(strategy_tree, monkeypatch):
    fake_dynamic(monkeypatch, integrity=["protected file changed: x"])
    monkeypatch.setattr(gate, "run_tests", lambda: pytest.fail("tests must not run"))
    report = gate.run_gate(strategy_tree / "candidates" / "good.py", date(2026, 10, 29), promote_on_pass=False)
    assert report["checks"] == {"integrity": ["protected file changed: x"]}
    assert (strategy_tree / "candidates" / "good.py").exists()


def test_run_gate_backtest_error(strategy_tree, monkeypatch):
    fake_dynamic(monkeypatch)

    def fail(*args):
        raise RuntimeError("exchange down")

    monkeypatch.setattr(common, "backtest", fail)
    report = gate.run_gate(strategy_tree / "candidates" / "good.py", date(2026, 10, 29), promote_on_pass=False)
    assert report["checks"]["backtest"] == ["exchange down"]


def test_acquire_lock(strategy_tree):
    assert gate.acquire_lock() is True
    assert gate.acquire_lock() is False
    gate.RUN_LOCK.unlink()


def test_stale_lock_is_cleared(strategy_tree):
    common.RUNS.mkdir(parents=True)
    gate.RUN_LOCK.touch()
    import os
    os.utime(gate.RUN_LOCK, (0, 0))
    assert gate.acquire_lock() is True


def test_main_validates_path(strategy_tree, tmp_path, capsys):
    (tmp_path / "elsewhere.py").write_text(GOOD)
    assert gate.main([str(tmp_path / "elsewhere.py")]) == 2


def test_main_busy(strategy_tree, monkeypatch):
    monkeypatch.setattr(gate, "acquire_lock", lambda: False)
    assert gate.main([str(strategy_tree / "candidates" / "good.py")]) == 3


def test_main_end_to_end(strategy_tree, monkeypatch, capsys):
    fake_dynamic(monkeypatch)
    sent = []
    monkeypatch.setattr(notify, "send", lambda text: sent.append(text) or True)
    assert gate.main([str(strategy_tree / "candidates" / "good.py")]) == 0
    assert sent and sent[0].startswith("Gate PASSED")
    out = json.loads(capsys.readouterr().out)
    assert out["passed"] and "out_of_sample_private" not in out
    assert len(list(gate.GATE_RESULTS.glob("*-GoodCandidate.json"))) == 1
    assert not gate.RUN_LOCK.exists()


def test_main_rejection_is_not_urgent(strategy_tree, monkeypatch, capsys):
    fake_dynamic(monkeypatch, oos_metrics={**GOOD_OOS, "total_trades": 1})
    sent = []
    monkeypatch.setattr(notify, "send", lambda text: sent.append(text) or True)
    assert gate.main([str(strategy_tree / "candidates" / "good.py")]) == 1
    assert sent == []


def test_is_urgent():
    ok = {"integrity": "ok", "static": "ok"}
    assert gate.is_urgent({"passed": True, "action": "promoted; bot reloaded", "checks": ok})
    assert not gate.is_urgent({"passed": True, "checks": ok})  # --no-promote
    assert not gate.is_urgent({"passed": False, "action": "rejected", "checks": ok})
    assert gate.is_urgent({"passed": False, "action": "rejected",
                           "checks": {"integrity": ["protected file changed: Makefile"]}})


# --- reload_bot ----------------------------------------------------------------

class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def set_api_env(monkeypatch):
    monkeypatch.setenv("API_USERNAME", "u")
    monkeypatch.setenv("API_PASSWORD", "p")


def test_reload_bot(monkeypatch):
    assert gate.reload_bot().startswith("bot not reloaded (KeyError)")  # credentials missing
    set_api_env(monkeypatch)
    seen = []
    monkeypatch.setattr(gate.urllib.request, "urlopen",
                        lambda req, timeout: seen.append(req) or FakeResponse(b"{}"))
    assert gate.reload_bot() == "bot reloaded"
    assert seen[0].get_header("Authorization") == "Basic dTpw"  # base64("u:p")
    assert seen[0].full_url == f"{common.BOT_API}/reload_config"

    def refuse(req, timeout):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(gate.urllib.request, "urlopen", refuse)
    assert gate.reload_bot().startswith("bot not reloaded (URLError)")


# --- common ---------------------------------------------------------------------

def test_windows():
    assert common.windows(date(2026, 10, 29)) == ("20250815-20260701", "20260701-")


@pytest.mark.parametrize("value, ok", [("20250901-20260101", True), ("20250901-", True),
                                       ("2025-09-01", False), ("20260101-20250901", False)])
def test_parse_timerange(value, ok):
    if ok:
        common.parse_timerange(value)
    else:
        with pytest.raises(ValueError):
            common.parse_timerange(value)


def test_current_strategy(strategy_tree):
    assert common.current_strategy() == "OldLive"


def test_run_tools_retries_transient_errors(monkeypatch):
    results = [completed(2, "", "Could not load markets"), completed(0, "ok")]
    calls = []
    monkeypatch.setattr(common.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or results.pop(0))
    monkeypatch.setattr(common.time, "sleep", lambda s: None)
    assert common.run_tools(["echo"]).stdout == "ok"
    assert calls == [["echo"], ["echo"]]


def test_run_tools_does_not_retry_real_errors(monkeypatch):
    calls = []
    monkeypatch.setattr(common.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or completed(1, "", "boom"))
    assert common.run_tools(["x"]).returncode == 1 and len(calls) == 1


def test_backtest_parses_last_json_line(monkeypatch):
    seen = []
    monkeypatch.setattr(common, "run_tools",
                        lambda args, **kw: seen.append(args) or completed(0, 'noise\n{"total_trades": 3}\n'))
    assert common.backtest("Cand", "20250815-20260701", "gate", detail=True) == {"total_trades": 3}
    assert "--enable-protections" in seen[0][2] and "--detail" in seen[0][2]
    monkeypatch.setattr(common, "run_tools", lambda args, **kw: completed(1, "", "boom"))
    with pytest.raises(RuntimeError, match="boom"):
        common.backtest("Cand", "20250815-20260701", "gate")


# --- research backtest wrapper ----------------------------------------------------

TODAY = date(2026, 10, 29)


def test_bt_validate():
    assert bt.validate("Cand", None, TODAY) == "20250815-20260701"
    assert bt.validate("Cand", "20251001-20260601", TODAY) == "20251001-20260601"
    for strategy, timerange in [("bad name", None), ("Cand", "20250101-20250901"),
                                ("Cand", "20251001-"), ("Cand", "20251001-20261001")]:
        with pytest.raises(ValueError):
            bt.validate(strategy, timerange, TODAY)


def test_bt_main(monkeypatch, capsys):
    monkeypatch.setattr(common, "backtest", lambda s, t, tag, detail: {"total_trades": 7})
    assert bt.main(["Cand"]) == 0
    assert json.loads(capsys.readouterr().out)["total_trades"] == 7
    assert bt.main(["Cand", "--timerange", "20261001-"]) == 1


# --- notify ------------------------------------------------------------------------

def test_notify(monkeypatch):
    assert notify.send("x") is False  # not configured
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    sent = []
    monkeypatch.setattr(notify.urllib.request, "urlopen",
                        lambda url, body, timeout: sent.append(body) or FakeResponse(b'{"ok": true}'))
    assert notify.send("y" * 5000) is True
    assert len(sent[0]) < 4200

    attempts, sleeps = [], []

    def down(*args, **kwargs):
        attempts.append(1)
        raise urllib.error.URLError("down")

    monkeypatch.setattr(notify.urllib.request, "urlopen", down)
    monkeypatch.setattr(notify.time, "sleep", sleeps.append)
    assert notify.send("z") is False
    assert len(attempts) == notify.ATTEMPTS and sleeps == [5, 10]

    flaky = iter([urllib.error.URLError("tls eof")])

    def recovers(*args, **kwargs):
        for exc in flaky:
            raise exc
        return FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(notify.urllib.request, "urlopen", recovers)
    assert notify.send("retry") is True


# --- bt_metrics --------------------------------------------------------------------

def test_bt_metrics_summarize():
    stats = {"strategy": {"S": {
        "total_trades": 2, "profit_total": 0.1, "trades": [{"leverage": 3.0}, {"leverage": 10.0}],
        "results_per_pair": [{"key": "BTC", "trades": 2, "profit_total_abs": 1.234},
                             {"key": "TOTAL", "trades": 2, "profit_total_abs": 1.234}],
        "exit_reason_summary": [{"key": "stop_loss", "trades": 1, "profit_total_abs": -2.0}],
    }}}
    out = bt_metrics.summarize(stats, "S", detail=True)
    assert out["max_leverage"] == 10.0 and out["total_trades"] == 2
    assert out["per_pair"] == [{"pair": "BTC", "trades": 2, "profit_abs": 1.23}]
    assert out["exit_reasons"][0]["reason"] == "stop_loss"
    assert "per_pair" not in bt_metrics.summarize(stats, "S")
    assert out["fees_abs"] == 0 and out["avg_hold_hours"] == 0


def test_bt_metrics_trading_costs():
    trades = [{"amount": 2.0, "open_rate": 100.0, "close_rate": 110.0, "fee_open": 0.0005, "fee_close": 0.0005,
               "funding_fees": -0.25, "trade_duration": 120},
              {"amount": 1.0, "open_rate": 50.0, "close_rate": 40.0, "fee_open": 0.0002, "fee_close": 0.0002,
               "funding_fees": 0.05, "trade_duration": 60}]
    assert bt_metrics.trading_costs(trades) == {"fees_abs": 0.23, "funding_abs": -0.2, "avg_hold_hours": 1.5}
    assert bt_metrics.trading_costs([]) == {"fees_abs": 0, "funding_abs": 0, "avg_hold_hours": 0.0}


def test_bt_metrics_main(monkeypatch, capsys):
    import freqtrade.data.btanalysis as bta

    monkeypatch.setattr(bta, "load_backtest_stats",
                        lambda path: {"strategy": {"S": {"total_trades": 1, "trades": []}}})
    bt_metrics.main(["some/dir", "S"])
    assert json.loads(capsys.readouterr().out)["total_trades"] == 1


# --- perf_snapshot -------------------------------------------------------------------

def test_perf_snapshot(monkeypatch, capsys):
    import perf_snapshot

    set_api_env(monkeypatch)
    replies = {
        "profit": {"trade_count": 3, "profit_all_coin": 1.5},
        "status": [{"pair": "BTC/USDT:USDT", "leverage": 5, "is_open": True}],
        "trades?limit=30&order_by_id=false": {"trades": [{"pair": "ETH/USDT:USDT", "is_open": False, "profit_abs": 2},
                                       {"pair": "BTC/USDT:USDT", "is_open": True}]},
        "show_config": {"strategy": "TrendRegimeV1", "dry_run": True, "state": "running"},
    }
    monkeypatch.setattr(perf_snapshot.urllib.request, "urlopen", lambda req, timeout: FakeResponse(
        json.dumps(replies[req.full_url.rsplit("/v1/", 1)[1]]).encode()))
    assert perf_snapshot.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["strategy"] == "TrendRegimeV1" and len(out["recent_closed"]) == 1
    assert out["open_trades"][0]["leverage"] == 5

    def down(req, timeout):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(perf_snapshot.urllib.request, "urlopen", down)
    assert perf_snapshot.main() == 1
