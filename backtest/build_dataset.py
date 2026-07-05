"""Step 2: Build the point-in-time feature dataset.

For each liquidated borrower: compute features over a 30-day window that
ENDS 30 days BEFORE the liquidation (so the model never sees the run-up
or the event itself - no lookahead leakage).

For controls: sample borrowers (from Borrow events) who were NEVER
liquidated in the lookback. IMPORTANT (v2 fix): controls are anchored at
a RANDOM borrow event from their history - not their first - so that
wallet age at the anchor is comparable to cases (whose anchor, a
liquidation, necessarily comes later in their Aave lifecycle). Anchoring
controls at first-borrow inflates the age signal artificially (confirmed
in round-1 analysis).

Both groups also get protocol-history features (prior borrow count,
cadence, recency) derived from the already-pulled event logs - see
backtest/protocol_features.py.

Point-in-time correctness note: api.features.compute_features computes
wallet_age_days relative to NOW. For a backtest anchored in the past
that leaks future age, so we re-derive age as (as_of_ts - first_seen_ts)
here before scoring.

Usage:
    python -m backtest.build_dataset --cases 300 --controls 300
Resumable: wallets already in dataset.jsonl are skipped on re-run.
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Dict, List

from api.etherscan import get_wallet_first_seen_ts
from api.features import compute_features
from backtest.protocol_features import index_events_by_wallet, protocol_features

PRE_EVENT_GAP_DAYS = 30   # feature window ends this many days before the event
WINDOW_DAYS = 30          # feature window length


def load_jsonl(path: Path) -> List[Dict]:
    rows = []
    if path.exists():
        for line in open(path):
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def all_events_per_wallet(rows: List[Dict]) -> Dict[str, List[Dict]]:
    by_wallet: Dict[str, List[Dict]] = {}
    for r in rows:
        by_wallet.setdefault(r["wallet"].lower(), []).append(r)
    for w in by_wallet:
        by_wallet[w].sort(key=lambda r: r["ts"])
    return by_wallet


def earliest_event_per_wallet(rows: List[Dict]) -> Dict[str, Dict]:
    """Keep each wallet's EARLIEST event (first liquidation is the outcome)."""
    best: Dict[str, Dict] = {}
    for r in rows:
        w = r["wallet"].lower()
        if w not in best or r["ts"] < best[w]["ts"]:
            best[w] = r
    return best


def point_in_time_features(wallet: str, event_ts: int, apikey: str) -> Dict:
    """Features over [event_ts - 60d, event_ts - 30d], age as-of window end."""
    now_ts = int(time.time())
    as_of_ts = event_ts - PRE_EVENT_GAP_DAYS * 86400
    offset_days = max(0, (now_ts - as_of_ts) // 86400)

    feats = compute_features(wallet, WINDOW_DAYS, int(offset_days), apikey)

    # Correct wallet age to the as-of date (no future leakage)
    first_seen_ts, _ = get_wallet_first_seen_ts(apikey, wallet)
    if first_seen_ts:
        feats["wallet_age_days"] = max(0, (as_of_ts - first_seen_ts) // 86400)
    feats["as_of_ts"] = int(as_of_ts)
    return feats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/backtest")
    ap.add_argument("--cases", type=int, default=300, help="Max liquidated wallets")
    ap.add_argument("--controls", type=int, default=300, help="Max control wallets")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    apikey = os.getenv("ETHERSCAN_API_KEY", "").strip()
    if not apikey:
        sys.exit("Set ETHERSCAN_API_KEY first.")

    data_dir = Path(args.data)
    liq = earliest_event_per_wallet(load_jsonl(data_dir / "liquidations.jsonl"))
    bor_rows = load_jsonl(data_dir / "borrowers.jsonl")
    bor_all = all_events_per_wallet(bor_rows)
    borrow_idx = index_events_by_wallet(bor_rows)
    if not liq or not bor_all:
        sys.exit("Run `python -m backtest.pull_events` first.")

    rng_anchor = random.Random(1337)
    liq_wallets = set(liq)
    # v2 anchoring fix: random borrow event per control wallet (see docstring)
    controls_pool = {w: rng_anchor.choice(evts)
                     for w, evts in bor_all.items() if w not in liq_wallets}
    print(f"Liquidated wallets: {len(liq):,} | never-liquidated borrowers: {len(controls_pool):,}")

    rng = random.Random(args.seed)
    cases = rng.sample(sorted(liq), min(args.cases, len(liq)))
    controls = rng.sample(sorted(controls_pool), min(args.controls, len(controls_pool)))

    out_path = data_dir / "dataset.jsonl"
    done = {json.loads(l)["wallet"] for l in open(out_path)} if out_path.exists() else set()
    todo = [(w, liq[w]["ts"], 1) for w in cases if w not in done] + \
           [(w, controls_pool[w]["ts"], 0) for w in controls if w not in done]

    # Rough cost: ~4 Etherscan calls/wallet at free-tier throttle
    est_min = len(todo) * 4 * 0.45 / 60
    print(f"To fetch: {len(todo)} wallets (already done: {len(done)}). "
          f"Estimated ~{est_min:.0f} min on free tier. Resumable - Ctrl-C anytime.")

    with open(out_path, "a") as out:
        for i, (wallet, event_ts, label) in enumerate(todo, 1):
            try:
                feats = point_in_time_features(wallet, event_ts, apikey)
            except Exception as e:
                print(f"  [{i}/{len(todo)}] {wallet} FAILED: {e}", file=sys.stderr)
                continue
            feats.update(protocol_features(wallet, feats["as_of_ts"], borrow_idx))
            feats["label_liquidated"] = label
            out.write(json.dumps(feats) + "\n")
            out.flush()
            if i % 10 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] done (last: {wallet}, label={label})")

    print(f"\nDataset -> {out_path}. Next: python -m backtest.run_backtest")


if __name__ == "__main__":
    main()
