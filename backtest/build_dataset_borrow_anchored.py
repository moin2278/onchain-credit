"""Round 3: borrow-anchored dataset (the production framing).

Prediction task: AT THE MOMENT OF A BORROW, will this wallet be
liquidated within the next 90 days?

Why this design is the gold standard here:
  - Cases AND controls are anchored at the SAME event type (a borrow),
    eliminating the anchor-type confounds found in rounds 1-2
    (first-borrow age artifact, never_borrowed_before artifact).
  - It is exactly how the product scores in production: at decision time.
  - Features use the 30 days ENDING AT the borrow (everything knowable
    at decision time - no leakage; the label lives strictly in the future).

Anchor selection:
  - Case: wallet has >=1 "trigger borrow" (a borrow followed by a
    liquidation within 90d). Anchor = earliest trigger borrow.
  - Control: wallet was NEVER liquidated in the lookback AND has >=1
    borrow that is at least 90 days old (so the outcome window is fully
    observed - newer borrows are censored). Anchor = random such borrow.
  - Wallets liquidated but with no trigger borrow (liquidation >90d
    after every borrow) are excluded as ambiguous.

Usage:
    python -m backtest.build_dataset_borrow_anchored --cases 300 --controls 300
Resumable like the other builders. Output: data/backtest/dataset.jsonl
(move/rename the round-2 dataset first if you want to keep it).
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

from api.etherscan import get_wallet_first_seen_ts
from api.features import compute_features
from backtest.protocol_features import index_events_by_wallet, protocol_features

OUTCOME_WINDOW_DAYS = 90
FEATURE_WINDOW_DAYS = 30


def load_jsonl(path: Path) -> List[Dict]:
    rows = []
    if path.exists():
        for line in open(path):
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def select_anchors(
    borrows_by_wallet: Dict[str, List[int]],
    liqs_by_wallet: Dict[str, List[int]],
    now_ts: int,
    rng: random.Random,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Return ({case_wallet: anchor_ts}, {control_wallet: anchor_ts}).

    Pure function - unit tested. Timestamps in seconds.
    """
    horizon = OUTCOME_WINDOW_DAYS * 86400
    cases: Dict[str, int] = {}
    controls: Dict[str, int] = {}

    for w, borrows in borrows_by_wallet.items():
        liqs = liqs_by_wallet.get(w, [])

        if liqs:
            # trigger borrows: borrow followed by a liquidation within 90d
            triggers = [b for b in borrows
                        if any(b < l <= b + horizon for l in liqs)]
            if triggers:
                cases[w] = min(triggers)
            # liquidated but no trigger borrow -> ambiguous, exclude
            continue

        # never liquidated: need a borrow with a fully-observed 90d window
        mature = [b for b in borrows if b <= now_ts - horizon]
        if mature:
            controls[w] = rng.choice(mature)

    return cases, controls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/backtest")
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--controls", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    apikey = os.getenv("ETHERSCAN_API_KEY", "").strip()
    if not apikey:
        sys.exit("Set ETHERSCAN_API_KEY first.")

    data_dir = Path(args.data)
    liq_rows = load_jsonl(data_dir / "liquidations.jsonl")
    bor_rows = load_jsonl(data_dir / "borrowers.jsonl")
    if not liq_rows or not bor_rows:
        sys.exit("Need liquidations.jsonl + borrowers.jsonl (run pull_events first).")

    borrow_idx = index_events_by_wallet(bor_rows)
    liq_idx = index_events_by_wallet(liq_rows)

    now_ts = int(time.time())
    rng = random.Random(args.seed)
    case_anchors, control_anchors = select_anchors(borrow_idx, liq_idx, now_ts, rng)
    print(f"Eligible: {len(case_anchors):,} case wallets, "
          f"{len(control_anchors):,} control wallets")

    cases = rng.sample(sorted(case_anchors), min(args.cases, len(case_anchors)))
    controls = rng.sample(sorted(control_anchors), min(args.controls, len(control_anchors)))

    out_path = data_dir / "dataset.jsonl"
    done = {json.loads(l)["wallet"] for l in open(out_path)} if out_path.exists() else set()
    todo = [(w, case_anchors[w], 1) for w in cases if w not in done] + \
           [(w, control_anchors[w], 0) for w in controls if w not in done]

    est_min = len(todo) * 4 * 0.45 / 60
    print(f"To fetch: {len(todo)} wallets (done: {len(done)}). "
          f"~{est_min:.0f} min on free tier. Resumable.")

    with open(out_path, "a") as out:
        for i, (wallet, anchor_ts, label) in enumerate(todo, 1):
            try:
                # Feature window ENDS AT the borrow (decision time)
                offset_days = max(0, (now_ts - anchor_ts) // 86400)
                feats = compute_features(wallet, FEATURE_WINDOW_DAYS,
                                         int(offset_days), apikey)
                first_seen_ts, _ = get_wallet_first_seen_ts(apikey, wallet)
                if first_seen_ts:
                    feats["wallet_age_days"] = max(0, (anchor_ts - first_seen_ts) // 86400)
                feats["as_of_ts"] = int(anchor_ts)
                # Protocol history strictly BEFORE the anchor borrow
                feats.update(protocol_features(wallet, anchor_ts, borrow_idx))
            except Exception as e:
                print(f"  [{i}/{len(todo)}] {wallet} FAILED: {e}", file=sys.stderr)
                continue
            feats["label_liquidated"] = label
            feats["anchor"] = "borrow_event"
            out.write(json.dumps(feats) + "\n")
            out.flush()
            if i % 10 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] done (last: {wallet}, label={label})")

    print(f"\nDataset -> {out_path}")
    print("Next: python -m backtest.run_backtest && python -m backtest.train_model")


if __name__ == "__main__":
    main()
