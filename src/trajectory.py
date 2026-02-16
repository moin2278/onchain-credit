from typing import Dict

def pct_change(curr: float, prev: float) -> float:
    if prev == 0:
        return 0.0
    return (curr - prev) / prev


def compute_trajectory(curr: Dict, prev: Dict) -> Dict:
    # Expecting these keys to exist in curr/prev:
    # tx_count, stablecoin_ratio, unique_counterparties, token_diversity, protocol_interactions

    deltas = {
        "tx_count": pct_change(curr.get("tx_count", 0), prev.get("tx_count", 0)),
        "stablecoin_ratio": pct_change(curr.get("stablecoin_ratio", 0), prev.get("stablecoin_ratio", 0)),
        "unique_counterparties": pct_change(curr.get("unique_counterparties", 0), prev.get("unique_counterparties", 0)),
        "token_diversity": pct_change(curr.get("token_diversity", 0), prev.get("token_diversity", 0)),
        "protocol_interactions": pct_change(curr.get("protocol_interactions", 0), prev.get("protocol_interactions", 0)),
    }

    drivers = []

    # Simple “why” rules (we’ll tune later)
    if deltas["stablecoin_ratio"] < -0.25:
        drivers.append("stablecoin usage dropping fast")
    if deltas["unique_counterparties"] > 0.50:
        drivers.append("counterparties spiking")
    if deltas["tx_count"] > 1.0:
        drivers.append("tx activity spike")

    trend = "stable"
    if len(drivers) >= 2:
        trend = "deteriorating"
    elif deltas["stablecoin_ratio"] > 0.20:
        trend = "improving"

    return {
        "trend": trend,
        "deltas": deltas,
        "drivers": drivers
    }