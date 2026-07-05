"""Temporal trajectory: compare current vs previous window features.

Consolidates the two previous implementations (api/ and src/) into one:
  - absolute deltas AND percent changes per feature
  - named "drivers" explaining WHY the trend moved (explainability)
  - overall direction: improving / stable / deteriorating
"""

from typing import Any, Dict, List

TRACKED_KEYS = [
    "consistency_score",
    "unique_tokens",
    "unique_counterparties",
    "stablecoin_ratio",
    "normal_tx_count",
    "internal_tx_count",
    "erc20_tx_count",
    "total_tx",
]


def pct_change(curr: float, prev: float) -> float:
    if prev == 0:
        return 0.0
    return round((curr - prev) / prev, 4)


def compute_trajectory(curr: Dict[str, Any], prev: Dict[str, Any]) -> Dict[str, Any]:
    deltas: Dict[str, float] = {}
    pct: Dict[str, float] = {}
    for k in TRACKED_KEYS:
        c = float(curr.get(k, 0) or 0)
        p = float(prev.get(k, 0) or 0)
        deltas[k] = round(c - p, 4)
        pct[k] = pct_change(c, p)

    drivers: List[str] = []
    if pct["stablecoin_ratio"] < -0.25:
        drivers.append("stablecoin usage dropping fast")
    if pct["stablecoin_ratio"] > 0.20:
        drivers.append("stablecoin usage increasing")
    if pct["unique_counterparties"] > 0.50:
        drivers.append("counterparties spiking")
    if pct["total_tx"] > 1.0:
        drivers.append("tx activity spike")
    if deltas["consistency_score"] < -0.15:
        drivers.append("activity consistency falling")
    if prev.get("total_tx", 0) > 0 and curr.get("total_tx", 0) == 0:
        drivers.append("wallet went dormant")

    negative = {
        "stablecoin usage dropping fast",
        "counterparties spiking",
        "tx activity spike",
        "activity consistency falling",
        "wallet went dormant",
    }
    positive = {"stablecoin usage increasing"}

    neg_n = sum(1 for d in drivers if d in negative)
    pos_n = sum(1 for d in drivers if d in positive)

    if neg_n >= 2:
        trend = "deteriorating"
    elif neg_n == 1 and pos_n == 0:
        trend = "slightly_deteriorating"
    elif pos_n > neg_n:
        trend = "improving"
    else:
        trend = "stable"

    return {
        "trend": trend,
        "deltas": deltas,
        "pct_change": pct,
        "drivers": drivers,
    }
