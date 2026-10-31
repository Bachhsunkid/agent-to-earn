from build_watchlist import select_pairs

NOW_MS = 1_800_000_000_000
OLD = str(NOW_MS - 500 * 86_400_000)
NEW = str(NOW_MS - 10 * 86_400_000)


def market(base, onboard=OLD, **overrides):
    m = {"swap": True, "linear": True, "active": True, "quote": "USDT", "settle": "USDT",
         "base": base, "info": {"contractType": "PERPETUAL", "onboardDate": onboard}}
    m.update(overrides)
    return m


def test_selects_top_volume_eligible_perps():
    markets = {
        "BTC/USDT:USDT": market("BTC"),
        "ETH/USDT:USDT": market("ETH"),
        "USDC/USDT:USDT": market("USDC"),
        "NEW/USDT:USDT": market("NEW", onboard=NEW),
        "OLD/USDC:USDC": market("OLD", quote="USDC", settle="USDC"),
        "DEAD/USDT:USDT": market("DEAD", active=False),
        "QTR/USDT:USDT": market("QTR", info={"contractType": "CURRENT_QUARTER", "onboardDate": OLD}),
        "SOL/USDT:USDT": market("SOL"),
    }
    tickers = {s: {"quoteVolume": v} for s, v in {
        "BTC/USDT:USDT": 900, "ETH/USDT:USDT": 800, "USDC/USDT:USDT": 10_000,
        "NEW/USDT:USDT": 5_000, "OLD/USDC:USDC": 5_000, "DEAD/USDT:USDT": 5_000,
        "QTR/USDT:USDT": 5_000, "SOL/USDT:USDT": 100}.items()}
    assert select_pairs(markets, tickers, top=2, min_age_days=400, now_ms=NOW_MS) == [
        "BTC/USDT:USDT", "ETH/USDT:USDT"]
    assert select_pairs(markets, tickers, top=10, min_age_days=400, now_ms=NOW_MS)[-1] == "SOL/USDT:USDT"
