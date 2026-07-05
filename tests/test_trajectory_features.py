import time

from api.etherscan import filter_by_ts
from api.features import aggregate_features
from api.trajectory import compute_trajectory, pct_change


# ---------- trajectory ----------

def test_pct_change_zero_prev():
    assert pct_change(10, 0) == 0.0


def test_deteriorating_when_multiple_negative_drivers():
    curr = {"stablecoin_ratio": 0.1, "unique_counterparties": 40, "total_tx": 300,
            "consistency_score": 0.2, "unique_tokens": 5,
            "normal_tx_count": 100, "internal_tx_count": 0, "erc20_tx_count": 200}
    prev = {"stablecoin_ratio": 0.5, "unique_counterparties": 10, "total_tx": 50,
            "consistency_score": 0.6, "unique_tokens": 5,
            "normal_tx_count": 20, "internal_tx_count": 0, "erc20_tx_count": 30}
    traj = compute_trajectory(curr, prev)
    assert traj["trend"] == "deteriorating"
    assert "stablecoin usage dropping fast" in traj["drivers"]
    assert "counterparties spiking" in traj["drivers"]


def test_improving_on_stablecoin_increase():
    curr = {"stablecoin_ratio": 0.6, "unique_counterparties": 10, "total_tx": 50,
            "consistency_score": 0.5, "unique_tokens": 5,
            "normal_tx_count": 20, "internal_tx_count": 0, "erc20_tx_count": 30}
    prev = {"stablecoin_ratio": 0.4, "unique_counterparties": 10, "total_tx": 50,
            "consistency_score": 0.5, "unique_tokens": 5,
            "normal_tx_count": 20, "internal_tx_count": 0, "erc20_tx_count": 30}
    assert compute_trajectory(curr, prev)["trend"] == "improving"


def test_dormant_wallet_driver():
    curr = {k: 0 for k in ["stablecoin_ratio", "unique_counterparties", "total_tx",
                           "consistency_score", "unique_tokens", "normal_tx_count",
                           "internal_tx_count", "erc20_tx_count"]}
    prev = dict(curr, total_tx=50, normal_tx_count=50)
    assert "wallet went dormant" in compute_trajectory(curr, prev)["drivers"]


# ---------- features ----------

WALLET = "0x" + "ab" * 20


def erc20_row(ts, frm, to, symbol="USDC", contract="0xtoken1"):
    return {"timeStamp": str(ts), "from": frm, "to": to,
            "tokenSymbol": symbol, "contractAddress": contract}


def test_aggregate_features_counts_and_diversity():
    now = int(time.time())
    erc20 = [
        erc20_row(now - 100, WALLET, "0xcp1", "USDC", "0xt1"),
        erc20_row(now - 200, "0xcp2", WALLET, "PEPE", "0xt2"),
        erc20_row(now - 90000, WALLET, "0xcp3", "DAI", "0xt3"),
    ]
    feats = aggregate_features(WALLET, 30, [], [], erc20, wallet_age_days=400, now_ts=now)
    assert feats["erc20_tx_count"] == 3
    assert feats["unique_tokens"] == 3
    assert feats["unique_counterparties"] == 3
    assert feats["stablecoin_ratio"] == round(2 / 3, 4)
    assert feats["active_days"] == 2
    assert feats["wallet_age_days"] == 400


def test_aggregate_features_empty():
    feats = aggregate_features(WALLET, 30, [], [], [], wallet_age_days=0)
    assert feats["total_tx"] == 0
    assert feats["stablecoin_ratio"] == 0.0
    assert feats["consistency_score"] == 0.0


# ---------- etherscan helpers ----------

def test_filter_by_ts():
    rows = [{"timeStamp": "100"}, {"timeStamp": "200"}, {"timeStamp": "bad"}, {}]
    assert filter_by_ts(rows, 150, 250) == [{"timeStamp": "200"}]
