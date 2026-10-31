import asyncio
import json
from datetime import UTC, datetime

import pytest

from dashboard import app as dash
from dashboard import donations as don
from dashboard import finance
from dashboard import public_snapshot as ps

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
EVM_WALLET = "0x69De327dffdc7c00fee516aa0761e9c144f4daa3"
TRON_WALLET = "TNEgwt4mEmzaickSVqawQAZ2LKY4uZAxM8"
DONOR = "0x1111111111111111111111111111111111111111"
SITE = {
    "started": "2026-10-29", "ends": "2027-01-29", "goal_multiple": 2, "vnd_per_usd": 25000,
    "costs_usd_per_month": [{"name": "Claude Pro", "usd": 20}, {"name": "VM", "usd": 10}],
    "donate": {"crypto": [
        {"label": "USDT (BEP20)", "network": "bsc", "address": EVM_WALLET},
        {"label": "USDT (ERC20)", "network": "eth", "address": EVM_WALLET},
        {"label": "USDT (TRC20)", "network": "tron", "address": TRON_WALLET},
        {"label": "USDT (BEP20)", "network": "bsc", "address": EVM_WALLET},  # duplicate
        {"label": "Old", "address": "0xabc"},  # no network: not tracked
    ]},
    "donors": {"names": {DONOR.upper().replace("0X", "0x"): "Alice"},
               "manual": [{"date": "2026-10-30", "via": "Momo", "amount": 50000, "currency": "VND",
                           "name": "Bob", "note": "Go Bit!"}]},
}


def log(block: int, amount: int, index: int = 0, contract: str = don.EVM["bsc"]["contract"], sender: str = DONOR):
    return {"address": contract, "topics": [don.TRANSFER_TOPIC, "0x" + sender[2:].rjust(64, "0"), "0x0"],
            "data": hex(amount), "blockNumber": hex(block), "transactionHash": f"0xtx{block}",
            "logIndex": hex(index), "removed": False, "blockTimestamp": hex(1793440000 + block)}


class FakeChain:
    """Answers JSON-RPC calls like a public node; records the getLogs ranges it was asked for."""

    def __init__(self, head: int, logs: list[dict], archive_below: int | None = None):
        self.head, self.logs, self.archive_below, self.ranges = head, logs, archive_below, []

    def __call__(self, url, payload=None, timeout=20):
        if payload["method"] == "eth_blockNumber":
            return {"result": hex(self.head)}
        query = payload["params"][0]
        start, end = int(query["fromBlock"], 16), int(query["toBlock"], 16)
        self.ranges.append((start, end))
        if self.archive_below is not None and start < self.archive_below:
            return {"error": {"code": -32602, "message": "Archive requests require a personal token"}}
        return {"result": [entry for entry in self.logs if start <= int(entry["blockNumber"], 16) <= end]}


def test_wallets_takes_tracked_networks_once():
    assert don.wallets(SITE) == [("bsc", EVM_WALLET), ("eth", EVM_WALLET), ("tron", TRON_WALLET)]


def test_evm_sync_scans_in_chunks_and_filters(monkeypatch):
    cfg = don.EVM["bsc"]
    head = 1_000_000
    safe_head = head - cfg["confirmations"]
    first = safe_head - cfg["lookback"]
    chain = FakeChain(head, [
        log(first + 10, 5 * 10**18),                                # 5 USDT
        log(first + 10, 5 * 10**18),                                # same log again: deduplicated
        log(first + 20, 10**17, index=1),                           # 0.1 USDT dust
        log(first + 30, 7 * 10**18, contract="0xfake"),             # look-alike token
        log(safe_head + 5, 9 * 10**18),                             # not confirmed yet
    ])
    monkeypatch.setattr(don, "http_json", chain)
    monkeypatch.setattr(don, "MAX_CHUNKS", 3)
    state = don.empty_state()
    don.sync_evm("bsc", EVM_WALLET, state, NOW)

    assert chain.ranges[0] == (first + 1, first + cfg["chunk"])
    assert len(chain.ranges) == don.MAX_CHUNKS  # the rest of the backlog waits for the next sync
    key = f"bsc:{EVM_WALLET.lower()}"
    assert state["cursors"][key] == first + don.MAX_CHUNKS * cfg["chunk"]
    assert list(state["transfers"].values()) == [
        {"id": f"0xtx{first + 10}:0", "network": "bsc", "tx": f"0xtx{first + 10}", "from": DONOR, "amount": 5.0,
         "time": don.iso(1793440000 + first + 10)}]

    while state["cursors"][key] < safe_head:
        don.sync_evm("bsc", EVM_WALLET, state, NOW)
    assert state["cursors"][key] == safe_head
    assert len(state["transfers"]) == 1


def test_evm_sync_skips_history_the_node_no_longer_has(monkeypatch):
    cfg = don.EVM["eth"]
    head = 500_000
    chain = FakeChain(head, [log(head - 100, 3 * 10**6, contract=cfg["contract"])],
                      archive_below=head - cfg["lookback"] - cfg["confirmations"])
    monkeypatch.setattr(don, "http_json", chain)
    key = f"eth:{EVM_WALLET.lower()}"
    state = don.empty_state() | {"cursors": {key: 100}}
    don.sync_evm("eth", EVM_WALLET, state, NOW)
    safe_head = head - cfg["confirmations"]
    assert state["gaps"] == [{"wallet": key, "from": 101, "to": safe_head - cfg["lookback"],
                              "at": "2026-10-31T12:00:00+00:00"}]
    assert state["cursors"][key] == safe_head
    assert [t["amount"] for t in state["transfers"].values()] == [3.0]


def test_evm_sync_reraises_other_rpc_errors(monkeypatch):
    def broken(url, payload=None, timeout=20):
        if payload["method"] == "eth_blockNumber":
            return {"result": hex(10**6)}
        return {"error": {"message": "limit exceeded"}}

    monkeypatch.setattr(don, "http_json", broken)
    with pytest.raises(don.RpcError, match="limit exceeded"):
        don.sync_evm("bsc", EVM_WALLET, don.empty_state(), NOW)


def test_tron_sync_pages_and_filters(monkeypatch):
    usdt = {"address": don.TRON["contract"]}
    pages = {
        "first": {"success": True, "data": [
            {"transaction_id": "t1", "token_info": usdt, "block_timestamp": 1793440000000, "from": "TDonor",
             "to": TRON_WALLET, "value": "25000000"},
            {"transaction_id": "t2", "token_info": usdt, "block_timestamp": 1793440000000, "from": TRON_WALLET,
             "to": "TOther", "value": "9000000"},                                   # outgoing
            {"transaction_id": "t3", "token_info": {"address": "TFake"}, "block_timestamp": 1793440000000,
             "from": "TSpam", "to": TRON_WALLET, "value": "9000000"},              # fake USDT
        ], "meta": {"links": {"next": "second"}}},
        "second": {"success": True, "data": [
            {"transaction_id": "t4", "token_info": usdt, "block_timestamp": 1793440000000, "from": "TSpam",
             "to": TRON_WALLET, "value": "100"},                                    # dust
        ], "meta": {}},
    }
    seen = []

    def fake(url, payload=None, timeout=20):
        seen.append(url)
        return pages["second" if url == "second" else "first"]

    monkeypatch.setattr(don, "http_json", fake)
    state = don.empty_state()
    don.sync_tron(TRON_WALLET, state, datetime(2026, 10, 29, tzinfo=UTC))
    assert f"/v1/accounts/{TRON_WALLET}/transactions/trc20?" in seen[0] and "min_timestamp=1793232000000" in seen[0]
    assert seen[1] == "second"
    assert state["transfers"] == {"t1": {"id": "t1", "network": "tron", "tx": "t1", "from": "TDonor",
                                         "amount": 25.0, "time": don.iso(1793440000)}}


def test_sync_isolates_failures_and_saves_atomically(tmp_path, monkeypatch):
    def fake_evm(network, address, state, now):
        if network == "eth":
            raise OSError("node down")
        state["transfers"]["x"] = {"id": "x"}

    monkeypatch.setattr(don, "sync_evm", fake_evm)
    monkeypatch.setattr(don, "sync_tron", lambda address, state, since: None)
    path = tmp_path / "finance" / "donations.json"
    errors = don.sync(SITE, path, NOW)
    assert errors == ["eth: OSError: node down"]
    state = json.loads(path.read_text())
    assert state["errors"] == errors and "x" in state["transfers"]
    assert set(state["synced"]) == {f"bsc:{EVM_WALLET}", f"tron:{TRON_WALLET}"}
    assert [p.name for p in path.parent.iterdir()] == ["donations.json"]
    assert don.load_state(tmp_path / "missing.json") == don.empty_state()


def state_with_transfers():
    return don.empty_state() | {"transfers": {
        "a": {"id": "a", "network": "bsc", "tx": "0xTX1", "from": DONOR, "amount": 5.0, "time": "2026-10-31T10:00:00+00:00"},
        "b": {"id": "b", "network": "tron", "tx": "t2", "from": "TAnon1234567890", "amount": 2.0,
              "time": "2026-10-29T10:00:00+00:00"},
    }}


def test_ledger_merges_chain_and_manual_entries():
    entries = don.ledger(SITE, state_with_transfers())
    assert [(e["via"], e["name"], e["usd"]) for e in entries] == [
        ("USDT BEP20", "Alice", 5.0), ("Momo", "Bob", 2.0), ("USDT TRC20", None, 2.0)]
    assert don.explorer_url(entries[0]) == "https://bscscan.com/tx/0xTX1"
    assert don.explorer_url(entries[1]) is None
    assert don.usd_value(50000, "VND", {}) is None  # no rate: shown, not counted
    assert don.usd_value("5", "USDT", {}) is None


def test_economy_keeps_donations_out_of_the_kpi():
    eco = finance.economy(SITE, profit=6.0, donations_usd=9.0, now=datetime(2026, 11, 8, tzinfo=UTC))
    daily = 30 * 12 / 365
    assert eco["monthly"] == 30 and eco["days"] == 10 and eco["season_days"] == 92
    assert eco["spent"] == pytest.approx(10 * daily) and eco["goal"] == pytest.approx(20 * daily)
    assert eco["progress"] == pytest.approx(6 / (20 * daily))
    assert eco["net"] == pytest.approx(6 + 9 - 10 * daily)
    assert eco["projected"]["profit"] == pytest.approx(6 / 10 * 92)
    assert eco["needed_return"] is None and eco["monthly_pace"] == pytest.approx(6 / 10 * 365 / 12)
    assert finance.economy(SITE, 6.0, 0, NOW, equity=300)["needed_return"] == {"breakeven": 0.1, "goal": 0.2}
    assert finance.economy({}, None, 0, NOW)["projected"] is None


def test_load_site_falls_back_to_example(tmp_path):
    example = tmp_path / "example.json"
    example.write_text('{"goal_multiple": 2}')
    assert finance.load_site(tmp_path / "missing.json", example) == {"goal_multiple": 2}
    assert finance.load_site(tmp_path / "a.json", tmp_path / "b.json") == {}


def test_snapshot_publishes_donors_without_wallets_and_says_thanks():
    entries = don.ledger(SITE, state_with_transfers())
    snap = ps.build(lambda path: (_ for _ in ()).throw(OSError()), [], [], [], {}, None, now=NOW, donations=entries)
    gifts = snap["donations"]
    assert gifts["count"] == 3 and gifts["total_usd"] == 9.0
    assert [d["who"] for d in gifts["items"]] == ["Alice", "Bob", "TAnon1…7890"]
    text = json.dumps(snap)
    for leaked in (DONOR, "0xTX1", "TAnon1234567890", '"t2"'):
        assert leaked not in text
    assert snap["mood"] == "down"  # bot down wins over thanks

    online = {"show_config": {"state": "running"}, "profit": {}, "status": [],
              "trades?limit=30&order_by_id=false": {"trades": []}, "daily?timescale=60": {"data": []}}
    assert ps.build(online.get, [], [], [], {}, None, now=NOW, donations=entries)["mood"] == "thankful"
    later = datetime(2026, 11, 2, tzinfo=UTC)
    assert ps.build(online.get, [], [], [], {}, None, now=later, donations=entries)["mood"] == "idle"
    assert ps.build(online.get, [], [], [], {}, None, now=NOW)["donations"] == {"count": 0, "total_usd": 0, "items": []}


def test_dashboard_finances_section(monkeypatch):
    bot = {"reachable": True, "dry_run": True, "profit": {"profit_all_coin": 4.0}, "equity": 300.0}
    state = state_with_transfers() | {"errors": ["eth: OSError: <down>"], "synced": {"bsc:x": "2026-10-31T11:55:00+00:00"},
                                      "gaps": [{"wallet": "eth:x", "from": 1, "to": 2, "at": "now"}]}
    site = SITE | {"donors": {**SITE["donors"], "names": {DONOR: "<b>Alice</b>"}}}
    page = dash.render_finances(site, bot, state, datetime(2026, 11, 8, tzinfo=UTC))
    assert "$9.00 from 3" in page and "KPI: profit ≥ 2× costs" in page and "paper" in page
    assert "&lt;b&gt;Alice&lt;/b&gt;" in page and "<b>Alice</b>" not in page
    assert "https://bscscan.com/tx/0xTX1" in page and "&lt;down&gt;" in page and "gap skipped" in page
    assert "Season end at this pace" in page and "bsc 11:55 UTC" in page
    assert "10.0% to break even, 20.0% for the goal · pace now $12.17/month" in page
    assert "bot unreachable" in dash.render_finances(SITE, {"reachable": False}, don.empty_state(), NOW)


def test_dashboard_donations_loop_logs_and_continues(tmp_path, monkeypatch, caplog):
    calls = []

    def fake_sync(site, path):
        calls.append(path)
        if len(calls) == 1:
            return ["bsc: RpcError: limit exceeded"]
        raise OSError("read-only")

    monkeypatch.setattr(don, "sync", fake_sync)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(dash.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(dash.donations_loop(tmp_path / "d.json"))
    assert len(calls) == 2 and sleeps == [dash.DONATIONS_INTERVAL] * 2
    assert "limit exceeded" in caplog.text and "read-only" in caplog.text
