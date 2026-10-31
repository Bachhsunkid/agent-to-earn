"""USDT donations to the wallets in public/site.json, plus entries the operator adds by hand.

The dashboard polls the chains every few minutes without API keys: public JSON-RPC nodes for
BNB Chain and Ethereum (eth_getLogs on the USDT contract, filtered by recipient) and TronGrid
for TRC20. Found transfers and the last scanned block per wallet live in a private state file
(user_data/finance/), so a restart or an RPC outage delays updates but loses nothing.

Only the real USDT contracts count, and transfers under MIN_USDT are ignored: address-poisoning
spam sends dust from look-alike wallets. Transfers that never touch a chain (Momo, internal
Binance transfers) come from `donors.manual` in site.json.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

MIN_USDT = 1.0
MAX_CHUNKS = 40  # eth_getLogs calls per wallet and sync; the rest waits for the next sync
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Public nodes keep only recent history, so a new wallet starts `lookback` blocks back (about a
# day) and a gap older than the node's history is skipped and recorded instead of retried forever.
EVM = {
    "bsc": {"rpc": "https://bsc-rpc.publicnode.com", "contract": "0x55d398326f99059ff775485246999027b3197955",
            "decimals": 18, "chunk": 2000, "confirmations": 15, "lookback": 190_000, "via": "USDT BEP20",
            "explorer": "https://bscscan.com/tx/"},
    "eth": {"rpc": "https://ethereum-rpc.publicnode.com", "contract": "0xdac17f958d2ee523a2206206994597c13d831ec7",
            "decimals": 6, "chunk": 2000, "confirmations": 12, "lookback": 7_200, "via": "USDT ERC20",
            "explorer": "https://etherscan.io/tx/"},
}
TRON = {"api": "https://api.trongrid.io", "contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t", "decimals": 6,
        "pages": 10, "via": "USDT TRC20", "explorer": "https://tronscan.org/#/transaction/"}
NETWORKS = (*EVM, "tron")


class RpcError(Exception):
    pass


def http_json(url: str, payload: dict | None = None, timeout: int = 30):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                          "User-Agent": "agent-to-earn-dashboard"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def rpc(url: str, method: str, params: list):
    reply = http_json(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if "error" in reply:
        raise RpcError(str(reply["error"].get("message", reply["error"]))[:200])
    return reply["result"]


def iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds")


def wallets(site: dict) -> list[tuple[str, str]]:
    found = []
    for w in (site.get("donate") or {}).get("crypto") or []:
        pair = (w.get("network"), (w.get("address") or "").strip())
        if pair[0] in NETWORKS and pair[1] and pair not in found:
            found.append(pair)
    return found


def add(state: dict, transfer: dict) -> None:
    if transfer["amount"] >= MIN_USDT:
        state["transfers"].setdefault(transfer["id"], transfer)


def sync_evm(network: str, address: str, state: dict, now: datetime) -> None:
    cfg = EVM[network]
    key = f"{network}:{address.lower()}"
    head = int(rpc(cfg["rpc"], "eth_blockNumber", []), 16) - cfg["confirmations"]
    cursor = state["cursors"].get(key, head - cfg["lookback"])
    recipient = "0x" + address.lower().removeprefix("0x").rjust(64, "0")
    for _ in range(MAX_CHUNKS):
        if cursor >= head:
            break
        end = min(head, cursor + cfg["chunk"])
        query = {"fromBlock": hex(cursor + 1), "toBlock": hex(end), "address": cfg["contract"],
                 "topics": [TRANSFER_TOPIC, None, recipient]}
        try:
            logs = rpc(cfg["rpc"], "eth_getLogs", [query])
        except RpcError as exc:
            skip_to = head - cfg["lookback"]
            if "archive" not in str(exc).lower() or skip_to <= cursor:
                raise
            state["gaps"].append({"wallet": key, "from": cursor + 1, "to": skip_to, "at": now.isoformat(timespec="seconds")})
            state["cursors"][key] = cursor = skip_to
            continue
        for log in logs:
            if log.get("address", "").lower() != cfg["contract"] or log.get("removed"):
                continue
            tx = log["transactionHash"]
            stamp = log.get("blockTimestamp") or rpc(cfg["rpc"], "eth_getBlockByNumber", [log["blockNumber"], False])["timestamp"]
            add(state, {"id": f"{tx}:{int(log['logIndex'], 16)}", "network": network, "tx": tx,
                        "from": "0x" + log["topics"][1][-40:], "amount": int(log["data"], 16) / 10 ** cfg["decimals"],
                        "time": iso(int(stamp, 16))})
        state["cursors"][key] = cursor = end


def sync_tron(address: str, state: dict, since: datetime) -> None:
    query = urllib.parse.urlencode({"only_to": "true", "only_confirmed": "true", "contract_address": TRON["contract"],
                                    "limit": 200, "min_timestamp": int(since.timestamp() * 1000)})
    url = f"{TRON['api']}/v1/accounts/{urllib.parse.quote(address)}/transactions/trc20?{query}"
    for _ in range(TRON["pages"]):
        page = http_json(url)
        if not page.get("success", True):
            raise RpcError(str(page.get("error", "TronGrid request failed"))[:200])
        for item in page.get("data", []):
            if item.get("to") != address or (item.get("token_info") or {}).get("address") != TRON["contract"]:
                continue
            tx = item["transaction_id"]
            add(state, {"id": tx, "network": "tron", "tx": tx, "from": item.get("from"),
                        "amount": int(item["value"]) / 10 ** TRON["decimals"], "time": iso(item["block_timestamp"] / 1000)})
        url = ((page.get("meta") or {}).get("links") or {}).get("next")
        if not url:
            break


def empty_state() -> dict:
    return {"version": 1, "cursors": {}, "transfers": {}, "gaps": [], "synced": {}, "errors": []}


def load_state(path: Path) -> dict:
    try:
        return empty_state() | json.loads(path.read_text())
    except (OSError, ValueError):
        return empty_state()


def save_state(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    os.replace(tmp, path)


def season_start(site: dict) -> datetime:
    try:
        return datetime.fromisoformat(site["started"]).replace(tzinfo=UTC)
    except (KeyError, TypeError, ValueError):
        return datetime(2026, 1, 1, tzinfo=UTC)


def sync(site: dict, path: Path, now: datetime | None = None) -> list[str]:
    """Scan every wallet; one failing network never blocks the others. Returns the errors."""
    now = now or datetime.now(UTC)
    state = load_state(path)
    errors = []
    for network, address in wallets(site):
        try:
            if network == "tron":
                sync_tron(address, state, season_start(site))
            else:
                sync_evm(network, address, state, now)
            state["synced"][f"{network}:{address}"] = now.isoformat(timespec="seconds")
        except (OSError, ValueError, KeyError, TypeError, RpcError) as exc:
            errors.append(f"{network}: {type(exc).__name__}: {exc}"[:300])
    state["errors"] = errors
    save_state(state, path)
    return errors


# --- ledger ------------------------------------------------------------------------

def usd_value(amount, currency: str, site: dict) -> float | None:
    if not isinstance(amount, (int, float)):
        return None
    if currency in ("USDT", "USD"):
        return float(amount)
    rate = site.get("vnd_per_usd")
    return amount / rate if currency == "VND" and isinstance(rate, (int, float)) and rate > 0 else None


def ledger(site: dict, state: dict) -> list[dict]:
    """On-chain and manual donations, newest first. `donors.names` maps a wallet or tx to a name."""
    donors = site.get("donors") or {}
    names = {str(k).lower(): v for k, v in (donors.get("names") or {}).items()}
    entries = []
    for t in state.get("transfers", {}).values():
        via = (EVM.get(t["network"]) or TRON)["via"]
        entries.append({"time": t["time"], "via": via, "amount": t["amount"], "currency": "USDT", "usd": t["amount"],
                        "name": names.get(t["tx"].lower()) or names.get(str(t["from"]).lower()), "note": None,
                        "from": t["from"], "tx": t["tx"], "network": t["network"]})
    for m in donors.get("manual") or []:
        currency = str(m.get("currency") or "USD").upper()
        entries.append({"time": str(m.get("date") or ""), "via": m.get("via") or "?", "amount": m.get("amount"),
                        "currency": currency, "usd": usd_value(m.get("amount"), currency, site), "name": m.get("name"),
                        "note": m.get("note"), "from": None, "tx": None, "network": None})
    return sorted(entries, key=lambda e: e["time"], reverse=True)


def explorer_url(entry: dict) -> str | None:
    cfg = EVM.get(entry.get("network")) or (TRON if entry.get("network") == "tron" else None)
    return cfg["explorer"] + entry["tx"] if cfg and entry.get("tx") else None
