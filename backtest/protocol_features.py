"""Protocol-history features derived from already-pulled Aave event logs.

These are position-aware signals (how the wallet actually behaves AS A
BORROWER) computed with zero additional API calls - everything comes from
data/backtest/borrowers.jsonl pulled in step 1.

All features are computed strictly BEFORE the as-of timestamp (no leakage).
"""

from collections import defaultdict
from typing import Dict, List


def index_events_by_wallet(rows: List[Dict]) -> Dict[str, List[int]]:
    """wallet -> sorted list of event timestamps."""
    idx = defaultdict(list)
    for r in rows:
        idx[r["wallet"].lower()].append(int(r["ts"]))
    return {w: sorted(ts) for w, ts in idx.items()}


def protocol_features(wallet: str, as_of_ts: int,
                      borrow_idx: Dict[str, List[int]]) -> Dict[str, float]:
    """Aave borrowing-history features as of a point in time."""
    ts_list = [t for t in borrow_idx.get(wallet.lower(), []) if t < as_of_ts]

    if not ts_list:
        return {
            "prior_borrow_count": 0,
            "borrow_span_days": 0.0,
            "days_since_last_borrow": -1.0,   # -1 = never borrowed before as-of
            "borrows_per_month": 0.0,
            "recent_borrow_burst": 0,
        }

    first, last = ts_list[0], ts_list[-1]
    span_days = max(0.0, (as_of_ts - first) / 86400)
    months = max(1.0, span_days / 30.0)
    recent_90d = sum(1 for t in ts_list if t >= as_of_ts - 90 * 86400)

    return {
        "prior_borrow_count": len(ts_list),
        "borrow_span_days": round(span_days, 1),
        "days_since_last_borrow": round((as_of_ts - last) / 86400, 1),
        "borrows_per_month": round(len(ts_list) / months, 3),
        "recent_borrow_burst": recent_90d,
    }
