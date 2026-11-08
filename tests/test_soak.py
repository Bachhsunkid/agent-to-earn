from datetime import datetime, timedelta

from soak_check import analyze, main, read_log

NOW = datetime(2026, 10, 30, 12, 0, 0)


def beat(ts: datetime) -> str:
    return f"{ts:%Y-%m-%d %H:%M:%S},123 - freqtrade.worker - INFO - Bot heartbeat. PID=1, version='2026.9', state='RUNNING'"


def run_for(minutes: int, skip: range = range(0)) -> list[str]:
    start = NOW - timedelta(minutes=minutes)
    return [beat(start + timedelta(minutes=i)) for i in range(minutes + 1) if i not in skip]


def test_full_uptime():
    report = analyze(run_for(600), NOW, hours=24)
    assert report["uptime"] == 1.0 and report["errors"] == 0 and report["hours"] == 10.0


def test_gap_counts_as_downtime():
    report = analyze(run_for(600, skip=range(100, 160)), NOW, hours=24)
    assert 0.89 < report["uptime"] < 0.91


def test_bot_down_at_the_end():
    lines = run_for(600)[:300]
    assert analyze(lines, NOW, hours=24)["uptime"] < 0.55


def test_errors_and_old_lines():
    old = beat(NOW - timedelta(days=3))
    err = f"{NOW - timedelta(minutes=5):%Y-%m-%d %H:%M:%S},1 - freqtrade.exchange - ERROR - boom"
    warn = f"{NOW - timedelta(minutes=4):%Y-%m-%d %H:%M:%S},1 - freqtrade.exchange - WARNING - meh"
    telegram = f"{NOW - timedelta(minutes=3):%Y-%m-%d %H:%M:%S},1 - telegram.ext.Updater - ERROR - Exception happened while polling for updates."
    report = analyze([old, "garbage", *run_for(60), err, warn, telegram], NOW, hours=24)
    assert report["errors"] == 1 and report["warnings"] == 1 and report["last_errors"][0].endswith("boom")
    assert report["telegram_errors"] == 1


def test_empty_log_is_down():
    assert analyze([], NOW, hours=1)["uptime"] == 0.0


def test_main(tmp_path, capsys):
    log = tmp_path / "ft.log"
    log.write_text("")
    assert main(["--log", str(log), "--hours", "1"]) == 1
    assert "result: FAIL" in capsys.readouterr().out


def test_read_log_includes_rotated_files_oldest_first(tmp_path):
    log = tmp_path / "ft.log"
    assert read_log(log) == []
    (tmp_path / "ft.log.2").write_text("a\n")
    (tmp_path / "ft.log.10").write_text("old\n")
    (tmp_path / "ft.log.1").write_text("b\n")
    (tmp_path / "ft.log.bak").write_text("ignored\n")
    log.write_text("c\n")
    assert read_log(log) == ["old", "a", "b", "c"]

