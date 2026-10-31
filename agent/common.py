"""Helpers shared by the gate, the research tools and the dashboard (standard library only).

They run inside the tools image (the `research` and `tools` compose services); secrets come
from environment variables that docker compose fills from .env.
"""

import json
import os
import re
import subprocess
import time
import uuid
from base64 import b64encode
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ROOT / "user_data" / "strategies"
LIVE = STRATEGIES / "live"
CANDIDATES = STRATEGIES / "candidates"
ARCHIVE = ROOT / "user_data" / "strategies_archive"
RESULTS = ROOT / "user_data" / "backtest_results"
RUNS = ROOT / "agent" / "runs"
STRATEGY_CONFIG = ROOT / "user_data" / "config.strategy.json"
BOT_API = os.environ.get("BOT_API", "http://127.0.0.1:8080/api/v1")

# First candle used for backtests (data starts 2025-08-01; the gap covers indicator warm-up).
DATA_START = date(2025, 8, 15)
# The most recent OOS_DAYS are held out: research tools cannot backtest them, only the gate.
OOS_DAYS = 120

STRATEGY_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]{2,48}$")
TIMERANGE_RE = re.compile(r"^(\d{8})-(\d{8})?$")
TRANSIENT_ERRORS = ("Could not load markets", "RequestTimeout", "NetworkError", "ExchangeNotAvailable")


def windows(today: date) -> tuple[str, str]:
    """In-sample and out-of-sample timeranges for backtests run on `today`."""
    oos_start = today - timedelta(days=OOS_DAYS)
    return f"{DATA_START:%Y%m%d}-{oos_start:%Y%m%d}", f"{oos_start:%Y%m%d}-"


def parse_timerange(value: str) -> tuple[date, date | None]:
    match = TIMERANGE_RE.match(value)
    if not match:
        raise ValueError(f"timerange must look like YYYYMMDD-YYYYMMDD, got {value!r}")
    start = datetime.strptime(match[1], "%Y%m%d").date()
    end = datetime.strptime(match[2], "%Y%m%d").date() if match[2] else None
    if end and end <= start:
        raise ValueError("timerange end must be after start")
    return start, end


def current_strategy() -> str:
    return json.loads(STRATEGY_CONFIG.read_text())["strategy"]


def api_auth() -> str:
    """Authorization header value for the Freqtrade REST API (KeyError if not configured)."""
    credentials = f"{os.environ['API_USERNAME']}:{os.environ['API_PASSWORD']}"
    return f"Basic {b64encode(credentials.encode()).decode()}"


def run_tools(args: list[str], retries: int = 3, timeout: int = 3600) -> subprocess.CompletedProcess:
    """Run a freqtrade/pytest command, retrying transient exchange/network failures."""
    for attempt in range(1, retries + 1):
        proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        output = proc.stdout + proc.stderr
        if proc.returncode == 0 or not any(e in output for e in TRANSIENT_ERRORS) or attempt == retries:
            return proc
        time.sleep(10 * attempt)
    raise AssertionError("unreachable")


def backtest(strategy: str, timerange: str, tag: str, detail: bool = False) -> dict:
    """Backtest `strategy` on `timerange` and return summary metrics."""
    out_dir = f"user_data/backtest_results/{tag}/{uuid.uuid4().hex[:8]}"
    script = (
        f"mkdir -p {out_dir} && freqtrade backtesting --config user_data/config.json"
        f" --strategy {strategy} --timerange {timerange} --enable-protections"
        f" --export trades --backtest-directory {out_dir}"
        f" && python agent/bt_metrics.py {out_dir} {strategy}{' --detail' if detail else ''}"
    )
    proc = run_tools(["sh", "-c", script])
    if proc.returncode != 0:
        raise RuntimeError(f"backtest of {strategy} on {timerange} failed:\n{tail(proc)}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def tail(proc: subprocess.CompletedProcess, lines: int = 25) -> str:
    return "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-lines:])
