"""Wallet feature computation.

Split into two layers:
  - aggregate_features(): pure function over already-fetched tx rows (unit-testable)
  - compute_features(): fetches from Etherscan, then aggregates
"""

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api.etherscan import fetch_action_desc, get_wallet_first_seen_ts

# Stablecoin symbols (best-effort; count-based, not USD-value-based yet)
STABLE_SYMBOLS = {
    "USDC", "USDT", "DAI", "TUSD", "USDP", "FDUSD", "FRAX", "LUSD", "GUSD",
}


def aggregate_features(
    wallet: str,
    window_days: int,
    normal: List[Dict[str, Any]],
    internal: List[Dict[str, Any]],
    erc20: List[Dict[str, Any]],
    wallet_age_days: int,
    truncated: bool = False,
    now_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pure aggregation of raw tx rows into wallet features. No network calls."""
    now_ts = now_ts or int(time.time())

    normal_count = len(normal)
    internal_count = len(internal)
    erc20_count = len(erc20)

    # Active days + max daily tx (burstiness input)
    day_counts: Dict[str, int] = {}
    for x in (normal + internal + erc20):
        try:
            ts = int(x.get("timeStamp", "0"))
        except Exception:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        day_counts[day] = day_counts.get(day, 0) + 1

    active_days = len(day_counts)
    max_daily_tx = max(day_counts.values()) if day_counts else 0
    total_tx = normal_count + internal_count + erc20_count

    consistency_score = round(active_days / max(1, window_days), 4)

    # Token + counterparty diversity, stablecoin share (from ERC20 transfers)
    unique_tokens = set()
    counterparties = set()
    stable_count = 0

    w = wallet.lower()
    for t in erc20:
        sym = str(t.get("tokenSymbol", "")).upper().strip()
        contract = str(t.get("contractAddress", "")).lower().strip()
        frm = str(t.get("from", "")).lower().strip()
        to = str(t.get("to", "")).lower().strip()

        if contract:
            unique_tokens.add(contract)

        if frm == w and to:
            counterparties.add(to)
        elif to == w and frm:
            counterparties.add(frm)

        if sym in STABLE_SYMBOLS:
            stable_count += 1

    stablecoin_ratio = round(stable_count / erc20_count, 4) if erc20_count else 0.0

    return {
        "wallet": wallet,
        "window_days": window_days,
        "wallet_age_days": int(wallet_age_days),
        "active_days": int(active_days),
        "max_daily_tx": int(max_daily_tx),
        "total_tx": int(total_tx),
        "consistency_score": float(consistency_score),
        "unique_tokens": len(unique_tokens),
        "unique_counterparties": len(counterparties),
        "stablecoin_ratio": float(stablecoin_ratio),
        "normal_tx_count": int(normal_count),
        "internal_tx_count": int(internal_count),
        "erc20_tx_count": int(erc20_count),
        "history_truncated": bool(truncated),
    }


def compute_features(wallet: str, window_days: int, offset_days: int, apikey: str) -> Dict[str, Any]:
    """Fetch tx history from Etherscan and aggregate into features."""
    now_ts = int(time.time())
    end_ts = now_ts - (offset_days * 86400)
    start_ts = end_ts - (window_days * 86400)

    errors: Dict[str, str] = {}
    truncated_any = False

    normal, err, trunc = fetch_action_desc(apikey, wallet, "txlist", start_ts, end_ts)
    if err:
        errors["normal"] = err
        normal = []
    truncated_any = truncated_any or trunc

    internal, err, trunc = fetch_action_desc(apikey, wallet, "txlistinternal", start_ts, end_ts)
    if err:
        errors["internal"] = err
        internal = []
    truncated_any = truncated_any or trunc

    erc20, err, trunc = fetch_action_desc(apikey, wallet, "tokentx", start_ts, end_ts)
    if err:
        errors["erc20"] = err
        erc20 = []
    truncated_any = truncated_any or trunc

    # Wallet age from FIRST EVER tx (not just the window)
    wallet_age_days = 0
    first_seen_ts, age_err = get_wallet_first_seen_ts(apikey, wallet)
    if age_err:
        errors["age"] = age_err
    if first_seen_ts:
        wallet_age_days = max(0, (now_ts - first_seen_ts) // 86400)

    feats = aggregate_features(
        wallet=wallet,
        window_days=window_days,
        normal=normal,
        internal=internal,
        erc20=erc20,
        wallet_age_days=wallet_age_days,
        truncated=truncated_any,
        now_ts=now_ts,
    )
    feats["offset_days"] = offset_days
    feats["data_ok"] = len(errors) == 0
    feats["errors"] = errors
    return feats
