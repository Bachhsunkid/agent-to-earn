"""Deterministic promotion gate for agent-written strategies.

Usage: python3 agent/gate.py user_data/strategies/candidates/<file>.py [--no-promote]

A candidate replaces the live strategy only if every check passes:
  1. guardrail files match agent/guardrails.lock
  2. static checks: one GuardedStrategy subclass, allowed imports, no escape hatches
  3. the test suite passes
  4. lookahead-analysis finds no bias
  5. in-sample and out-of-sample backtests meet CRITERIA and beat the live strategy out of
     sample, at a fixed stake both with and without each side's single best trade
Passing candidates move to live/ and the bot reloads; failing ones move to the archive.
Within PROMOTION_COOLDOWN of the last promotion the gate stops after the integrity check and
leaves the candidate in candidates/, so the live strategy keeps trading long enough to judge.
The agent sees pass/fail per out-of-sample criterion, never the out-of-sample numbers.
"""

import argparse
import ast
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import common
import notify

LOCK_FILE = common.ROOT / "agent" / "guardrails.lock"
PROTECTED = [
    "user_data/strategies/guarded_strategy.py",
    "user_data/config.json",
    "user_data/config.live.json",
    "user_data/config.rpc.json",
    "docker-compose.yml",
    "docker/Dockerfile.tools",
    "docker/bot-entrypoint.sh",
    "Makefile",
    "pytest.ini",
    "agent/gate.py",
    "agent/common.py",
    "agent/bt.py",
    "agent/bt_metrics.py",
    "agent/notify.py",
    "agent/perf_snapshot.py",
    "agent/readiness.py",
    "agent/LOOP.md",
    "agent/loop.settings.json",
    "agent/run_loop.sh",
    "agent/scheduler.sh",
    "scripts/build_universe.py",
    "dashboard/app.py",
    "dashboard/public_snapshot.py",
    "dashboard/donations.py",
    "dashboard/finance.py",
    "public/app.py",
    "tests/conftest.py",
    "tests/test_guarded_strategy.py",
    "tests/test_gate.py",
]
GATE_RESULTS = common.RUNS / "gate"
RUN_LOCK = common.RUNS / ".gate.lock"
STALE_LOCK_SECONDS = 3 * 3600
# At about 10 trades a month a strategy needs weeks of paper trading before it can be
# judged, and every promotion restarts that clock (docs/adr/0008-promotion-cooldown.md).
PROMOTION_COOLDOWN = timedelta(days=14)

CRITERIA = {
    "in_sample": {"min_trades": 40, "min_profit_factor": 1.0, "max_drawdown": 0.30},
    "out_of_sample": {"min_trades": 15, "min_profit_factor": 1.1, "min_profit": 0.0,
                      "max_drawdown": 0.20},
}
MAX_LEVERAGE = 10.0
# Candidate may not be meaningfully riskier than the live strategy out of sample.
MAX_EXTRA_DRAWDOWN = 0.05

ALLOWED_IMPORTS = frozenset({
    "datetime", "functools", "math", "typing", "numpy", "pandas", "talib", "talib.abstract",
    "technical", "technical.indicators", "freqtrade.strategy",
    "freqtrade.vendor.qtpylib.indicators", "guarded_strategy",
})
FORBIDDEN_NAMES = frozenset({
    "exec", "eval", "compile", "open", "__import__", "globals", "locals", "vars", "setattr",
    "getattr", "delattr", "input", "breakpoint", "exit", "quit", "os", "sys", "subprocess",
    "socket", "shutil", "pathlib", "importlib", "builtins", "__builtins__",
})


# --- integrity -----------------------------------------------------------------

def file_hashes(paths: list[str] = PROTECTED, root: Path = common.ROOT) -> dict[str, str]:
    return {p: hashlib.sha256((root / p).read_bytes()).hexdigest() if (root / p).exists() else "missing"
            for p in paths}


def write_lock(lock_file: Path = LOCK_FILE, root: Path = common.ROOT) -> None:
    lock_file.write_text(json.dumps(file_hashes(PROTECTED, root), indent=2) + "\n")


def check_integrity(lock_file: Path = LOCK_FILE, root: Path = common.ROOT) -> list[str]:
    if not lock_file.exists():
        return ["guardrails.lock missing (run: make lock)"]
    expected = json.loads(lock_file.read_text())
    actual = file_hashes(list(expected), root)
    errors = [f"protected file changed: {p}" for p in expected if actual[p] != expected[p]]
    errors += [f"protected file not locked: {p}" for p in PROTECTED if p not in expected]
    return errors


# --- static checks -------------------------------------------------------------

def guarded_members(source: str | None = None) -> set[str]:
    source = source or (common.STRATEGIES / "guarded_strategy.py").read_text()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "GUARDED_MEMBERS" for t in node.targets):
            return {elt.value for elt in node.value.args[0].elts}
    raise ValueError("GUARDED_MEMBERS not found in guarded_strategy.py")


def class_names(paths) -> set[str]:
    names = set()
    for path in paths:
        try:
            tree = ast.parse(Path(path).read_text())
        except (OSError, SyntaxError):
            continue
        names |= {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    return names


def _is_constant_assign(node: ast.stmt) -> bool:
    targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
    return (isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
            and isinstance(node.value, ast.Constant)
            and all(isinstance(t, ast.Name) for t in targets))


def static_check(source: str, taken_names: set[str], guarded: set[str]) -> tuple[str | None, list[str]]:
    """Return (class name, violations) for a candidate strategy source."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return None, [f"syntax error: {exc}"]
    errors: list[str] = []
    classes = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            errors += [f"import not allowed: {a.name}" for a in node.names if a.name not in ALLOWED_IMPORTS]
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "") not in ALLOWED_IMPORTS:
                errors.append(f"import not allowed: {'.' * node.level}{node.module or ''}")
        elif isinstance(node, ast.ClassDef):
            classes.append(node)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # docstring
        elif not _is_constant_assign(node):
            errors.append(f"top-level statement not allowed (line {node.lineno})")

    if len(classes) != 1:
        errors.append(f"expected exactly one class, found {len(classes)}")
    for cls in classes:
        bases = [b.id for b in cls.bases if isinstance(b, ast.Name)]
        if bases != ["GuardedStrategy"] or len(cls.bases) != 1 or cls.keywords:
            errors.append(f"{cls.name} must inherit only from GuardedStrategy")
        if cls.decorator_list:
            errors.append(f"{cls.name} must not use class decorators")
        if not common.STRATEGY_NAME_RE.match(cls.name):
            errors.append(f"invalid class name: {cls.name}")
        if cls.name in taken_names:
            errors.append(f"class name already used: {cls.name}")
        members = set()
        for item in cls.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                members.add(item.name)
            elif isinstance(item, ast.Assign):
                members |= {t.id for t in item.targets if isinstance(t, ast.Name)}
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                members.add(item.target.id)
        errors += [f"overrides guarded member: {m}" for m in sorted(members & guarded)]

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            errors.append(f"forbidden name: {node.id} (line {node.lineno})")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            errors.append(f"dunder attribute access: {node.attr} (line {node.lineno})")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            errors.append(f"global/nonlocal not allowed (line {node.lineno})")
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and node not in tree.body:
            errors.append(f"imports must be at module level (line {node.lineno})")
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            flat = [e for t in targets for e in (t.elts if isinstance(t, ast.Tuple) else [t])]
            for target in flat:
                if isinstance(target, ast.Attribute) and not (
                        isinstance(target.value, ast.Name) and target.value.id == "self"):
                    errors.append(f"attribute assignment outside self (line {node.lineno})")
    return (classes[0].name if len(classes) == 1 else None), sorted(set(errors))


# --- dynamic checks ------------------------------------------------------------

def run_tests() -> list[str]:
    proc = common.run_tools(["pytest", "-q", "-p", "no:cacheprovider"])
    return [] if proc.returncode == 0 else [f"test suite failed:\n{common.tail(proc)}"]


def lookahead(strategy: str, timerange: str) -> list[str]:
    out = f"user_data/backtest_results/gate/lookahead-{strategy}.csv"
    (common.ROOT / out).parent.mkdir(parents=True, exist_ok=True)
    (common.ROOT / out).unlink(missing_ok=True)
    proc = common.run_tools([
        "freqtrade", "lookahead-analysis", "--config", "user_data/config.json",
        "--strategy", strategy, "--timerange", timerange, "--minimum-trade-amount", "10",
        "--targeted-trade-amount", "20", "--lookahead-analysis-exportfilename", out,
        "--backtest-directory", "user_data/backtest_results/gate",
    ])
    if proc.returncode != 0:
        return [f"lookahead-analysis failed:\n{common.tail(proc)}"]
    rows = [r for r in csv.DictReader((common.ROOT / out).open()) if r["strategy"] == strategy]
    if not rows:
        return ["lookahead-analysis produced no result (too few trades?)"]
    return [f"lookahead bias detected: {r}" for r in rows if r["has_bias"] != "False"]


def evaluate(metrics: dict, rules: dict) -> list[str]:
    failures = []
    if (metrics.get("total_trades") or 0) < rules["min_trades"]:
        failures.append("min_trades")
    if (metrics.get("profit_factor") or 0) < rules["min_profit_factor"]:
        failures.append("min_profit_factor")
    if "min_profit" in rules and (metrics.get("profit_total") or 0) <= rules["min_profit"]:
        failures.append("min_profit")
    if (metrics.get("max_drawdown_account") or 0) > rules["max_drawdown"]:
        failures.append("max_drawdown")
    if (metrics.get("max_leverage") or 0) > MAX_LEVERAGE + 1e-9:
        failures.append("max_leverage")
    return failures


def beats_incumbent(candidate: dict, incumbent: dict | None) -> list[str]:
    if incumbent is None:
        return []
    failures = []
    # Fixed-stake profit, so one early outlier cannot inflate every later trade; and again
    # without each side's best trade, so one outlier cannot decide the comparison.
    for key, name in (("profit_fixed_abs", "beat_live_profit"),
                      ("profit_fixed_ex_best_abs", "beat_live_profit_ex_best")):
        if (candidate.get(key) or 0) <= (incumbent.get(key) or 0):
            failures.append(name)
    if (candidate.get("max_drawdown_account") or 0) > (incumbent.get("max_drawdown_account") or 0) + MAX_EXTRA_DRAWDOWN:
        failures.append("beat_live_drawdown")
    return failures


def incumbent_oos(strategy: str, oos_range: str, starting_balance: float | None = None) -> dict | None:
    cache = GATE_RESULTS / f"incumbent-{strategy}-{oos_range.rstrip('-')}.json"
    if cache.exists():
        cached = json.loads(cache.read_text())
        # Older caches lack the fixed-stake metrics, and profits in USDT are only comparable
        # at the candidate's starting balance.
        if "profit_fixed_ex_best_abs" in cached and (
                starting_balance is None or cached.get("starting_balance") == starting_balance):
            return cached
    try:
        metrics = common.backtest(strategy, oos_range, "gate")
    except RuntimeError:
        return None
    cache.write_text(json.dumps(metrics))
    return metrics


def promotions_paused_until(now: datetime) -> datetime | None:
    """End of the cooldown after the last promotion, if it has not passed yet."""
    promoted = []
    for path in GATE_RESULTS.glob("2*.json"):  # gate reports, not the incumbent-* caches
        try:
            report = json.loads(path.read_text())
            if str(report.get("action", "")).startswith("promoted"):
                promoted.append(datetime.fromisoformat(report["time"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    until = max(promoted, default=None)
    return until + PROMOTION_COOLDOWN if until and until + PROMOTION_COOLDOWN > now else None


# --- outcome -----------------------------------------------------------------

def promote(candidate: Path, class_name: str) -> None:
    retired = common.ARCHIVE / "retired"
    retired.mkdir(parents=True, exist_ok=True)
    for old in common.LIVE.glob("*.py"):
        shutil.move(old, retired / old.name)
    shutil.move(candidate, common.LIVE / candidate.name)
    common.STRATEGY_CONFIG.write_text(json.dumps({"strategy": class_name}, indent=2) + "\n")


def reject(candidate: Path) -> None:
    rejected = common.ARCHIVE / "rejected"
    rejected.mkdir(parents=True, exist_ok=True)
    shutil.move(candidate, rejected / candidate.name)


def reload_bot() -> str:
    """Ask the running bot to reload its config (and thus the live strategy)."""
    try:
        req = urllib.request.Request(f"{common.BOT_API}/reload_config", method="POST",
                                     headers={"Authorization": common.api_auth()})
        with urllib.request.urlopen(req, timeout=10):
            return "bot reloaded"
    except (OSError, KeyError, ValueError) as exc:
        return f"bot not reloaded ({type(exc).__name__}); restart it to pick up the new strategy"


def acquire_lock() -> bool:
    common.RUNS.mkdir(parents=True, exist_ok=True)
    if RUN_LOCK.exists() and time.time() - RUN_LOCK.stat().st_mtime > STALE_LOCK_SECONDS:
        RUN_LOCK.unlink()
    try:
        os.close(os.open(RUN_LOCK, os.O_CREAT | os.O_EXCL))
        return True
    except FileExistsError:
        return False


def run_gate(candidate: Path, today: date, promote_on_pass: bool = True) -> dict:
    now = datetime.now(UTC)
    report: dict = {"candidate": candidate.name, "time": now.isoformat(timespec="seconds"),
                    "checks": {}, "passed": False}

    def step(name: str, errors: list[str]) -> bool:
        report["checks"][name] = errors or "ok"
        return not errors

    in_range, oos_range = common.windows(today)
    taken = class_names([*common.LIVE.glob("*.py"), *common.ARCHIVE.rglob("*.py"),
                         *(p for p in common.CANDIDATES.glob("*.py") if p != candidate)])
    class_name, static_errors = static_check(candidate.read_text(), taken, guarded_members())
    report["strategy"] = class_name
    ok = step("integrity", check_integrity())
    paused = promotions_paused_until(now) if ok and promote_on_pass else None
    if paused:
        step("cooldown", [f"promotions paused until {paused:%Y-%m-%d %H:%M} UTC"])
        report["action"] = "deferred; the candidate stays in candidates/"
        return report
    ok = ok and step("static", static_errors) and step("tests", run_tests())
    if ok:
        ok = step("lookahead", lookahead(class_name, in_range))
    if ok:
        try:
            m_in = common.backtest(class_name, in_range, "gate")
            m_oos = common.backtest(class_name, oos_range, "gate")
        except RuntimeError as exc:
            ok = step("backtest", [str(exc)])
        else:
            report["in_sample"] = m_in
            report["out_of_sample_private"] = m_oos
            oos_failures = evaluate(m_oos, CRITERIA["out_of_sample"]) + beats_incumbent(
                m_oos, incumbent_oos(common.current_strategy(), oos_range, m_oos.get("starting_balance")))
            ok = step("in_sample", evaluate(m_in, CRITERIA["in_sample"])) & step("out_of_sample", oos_failures)
    report["passed"] = ok
    if promote_on_pass:
        if ok:
            promote(candidate, class_name)
            report["action"] = f"promoted; {reload_bot()}"
        else:
            reject(candidate)
            report["action"] = "rejected"
    return report


def public_view(report: dict) -> dict:
    """What the research agent may see: no out-of-sample numbers."""
    return {k: v for k, v in report.items() if k != "out_of_sample_private"}


def summary_text(report: dict) -> str:
    failed = {k: v for k, v in report["checks"].items() if v != "ok"}
    lines = [f"Gate {'PASSED' if report['passed'] else 'FAILED'}: {report.get('strategy') or report['candidate']}",
             f"action: {report.get('action', 'none')}"]
    if "in_sample" in report:
        m = report["in_sample"]
        lines.append(f"in-sample: {m['total_trades']} trades, profit {m['profit_total']:.1%}, "
                     f"PF {m['profit_factor']:.2f}, DD {m['max_drawdown_account']:.1%}")
    lines += [f"{k}: {v if isinstance(v, str) else '; '.join(v)[:300]}" for k, v in failed.items()]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--no-promote", action="store_true")
    args = parser.parse_args(argv)

    candidate = args.candidate.resolve()
    if candidate.parent != common.CANDIDATES.resolve() or candidate.suffix != ".py" or not candidate.exists():
        print(f"error: candidate must be an existing .py file in {common.CANDIDATES}/")
        return 2
    if not acquire_lock():
        print("error: another gate run is in progress")
        return 3
    try:
        report = run_gate(candidate, date.today(), promote_on_pass=not args.no_promote)
    finally:
        RUN_LOCK.unlink(missing_ok=True)

    GATE_RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (GATE_RESULTS / f"{stamp}-{report.get('strategy') or candidate.stem}.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(public_view(report), indent=1))
    if is_urgent(report):
        notify.send(summary_text(report))
    return 0 if report["passed"] else 1


def is_urgent(report: dict) -> bool:
    """Telegram is for urgent news only: a new live strategy, or tampered guardrails.
    Everything else is shown on the dashboard."""
    return bool(report["passed"] and report.get("action", "").startswith("promoted")) or (
        report["checks"].get("integrity", "ok") != "ok")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
