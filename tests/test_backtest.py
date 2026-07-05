import json

from backtest import topic_to_address
from backtest.build_dataset import earliest_event_per_wallet
from backtest.run_backtest import analyze


def test_topic_to_address():
    topic = "0x000000000000000000000000" + "ab" * 20
    assert topic_to_address(topic) == "0x" + "ab" * 20


def test_earliest_event_per_wallet():
    rows = [
        {"wallet": "0xA", "ts": 200, "tx_hash": "t2"},
        {"wallet": "0xa", "ts": 100, "tx_hash": "t1"},
        {"wallet": "0xB", "ts": 300, "tx_hash": "t3"},
    ]
    best = earliest_event_per_wallet(rows)
    assert best["0xa"]["ts"] == 100  # earliest kept, case-normalized
    assert best["0xb"]["ts"] == 300


def _feats(wallet, label, *, age, tokens, cps, consistency, stable, total, erc20):
    return {
        "wallet": wallet, "window_days": 30, "wallet_age_days": age,
        "active_days": int(consistency * 30), "max_daily_tx": 3,
        "total_tx": total, "consistency_score": consistency,
        "unique_tokens": tokens, "unique_counterparties": cps,
        "stablecoin_ratio": stable, "normal_tx_count": total - erc20,
        "internal_tx_count": 0, "erc20_tx_count": erc20,
        "history_truncated": False, "data_ok": True, "errors": {},
        "label_liquidated": label,
    }


def test_analyze_separates_good_and_bad_wallets():
    rows = []
    # 10 strong wallets, 1 liquidated
    for i in range(10):
        rows.append(_feats(f"0xgood{i}", 1 if i == 0 else 0,
                           age=900, tokens=12, cps=25, consistency=0.6,
                           stable=0.4, total=100, erc20=60))
    # 10 weak wallets, 7 liquidated
    for i in range(10):
        rows.append(_feats(f"0xbad{i}", 1 if i < 7 else 0,
                           age=40, tokens=1, cps=1, consistency=0.05,
                           stable=0.0, total=6, erc20=3))

    s = analyze(rows)
    assert s["total_wallets"] == 20
    assert s["total_liquidated"] == 8
    assert "LOW" in s["tiers"] and "HIGH" in s["tiers"]
    # HIGH tier must show a higher realized liquidation rate than LOW
    assert s["tiers"]["HIGH"]["liquidation_rate"] > s["tiers"]["LOW"]["liquidation_rate"]
    assert s["high_vs_low_ratio"] and s["high_vs_low_ratio"] > 1
    assert s["capture"]["capture_rate"] > 0.5


def test_analyze_handles_empty_tiers():
    rows = [_feats("0xw", 0, age=900, tokens=12, cps=25,
                   consistency=0.6, stable=0.4, total=100, erc20=60)]
    s = analyze(rows)
    assert s["base_liquidation_rate"] == 0.0
    assert s["high_vs_low_ratio"] is None


def test_protocol_features_point_in_time():
    from backtest.protocol_features import index_events_by_wallet, protocol_features
    rows = [
        {"wallet": "0xW", "ts": 1000}, {"wallet": "0xw", "ts": 2000},
        {"wallet": "0xW", "ts": 9000},  # after as_of - must be excluded
        {"wallet": "0xOther", "ts": 500},
    ]
    idx = index_events_by_wallet(rows)
    pf = protocol_features("0xw", as_of_ts=5000, borrow_idx=idx)
    assert pf["prior_borrow_count"] == 2          # 9000 excluded (leakage guard)
    assert pf["days_since_last_borrow"] == round(3000 / 86400, 1)
    none = protocol_features("0xnobody", 5000, idx)
    assert none["prior_borrow_count"] == 0
    assert none["days_since_last_borrow"] == -1.0


def test_borrow_anchored_selection():
    import random
    from backtest.build_dataset_borrow_anchored import select_anchors
    D = 86400
    now = 1_000 * D
    borrows = {
        "0xcase": [100 * D, 200 * D],       # liq at 230d -> 200d borrow triggers
        "0xslow": [100 * D],                # liq at 400d -> >90d after, ambiguous
        "0xctl":  [500 * D, 950 * D],       # never liq; 950d too recent (censored)
        "0xnew":  [980 * D],                # never liq; no mature borrow
    }
    liqs = {"0xcase": [230 * D], "0xslow": [400 * D]}
    cases, controls = select_anchors(borrows, liqs, now, random.Random(0))
    assert cases == {"0xcase": 200 * D}          # earliest TRIGGER borrow
    assert "0xslow" not in cases and "0xslow" not in controls  # ambiguous excluded
    assert controls == {"0xctl": 500 * D}        # only the mature borrow
    assert "0xnew" not in controls               # censored window excluded
