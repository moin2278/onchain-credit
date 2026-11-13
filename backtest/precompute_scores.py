"""Warm-precompute batch: score active Aave V3 borrowers into the DB.

Enumerates recent Aave V3 Borrow events (newest blocks first), dedupes
wallets, and scores each with the SAME pipeline the API uses
(live_model_features -> score_with_model), upserting into Supabase.

Resumable: wallets already scored within the freshness window are skipped,
so repeated runs extend coverage. Time-budgeted so it fits a scheduled job.

Usage:
    export ETHERSCAN_API_KEY=...   DATABASE_URL=...
    python -m backtest.precompute_scores --months 3 --limit 1500 --max-minutes 240
"""

import argparse
import os
import sys
import time
from typing import List

from api import store
from api.etherscan import etherscan_v2_call
from api.model_scoring import load_model, live_model_features, score_with_model
from backtest import AAVE_V3_BORROW_TOPIC0, AAVE_V3_POOL, topic_to_address
from backtest.pull_events import get_block_by_time, get_latest_block

BORROW_TOPIC_INDEX = 2      # Borrow event: topics[2] == onBehalfOf (borrower)
PAGE_SIZE = 1000
BLOCKS_PER_CHUNK = 40_000   # ~5.5 days of mainnet blocks


def enumerate_borrowers(apikey: str, from_block: int, to_block: int, cap: int) -> List[str]:
    """Distinct borrower wallets from Aave V3 Borrow logs, newest blocks first."""
    seen = set()
    wallets: List[str] = []
    chunk_end = to_block
    while chunk_end >= from_block and len(wallets) < cap:
        chunk_start = max(from_block, chunk_end - BLOCKS_PER_CHUNK + 1)
        page = 1
        while True:
            data = etherscan_v2_call({
                "chainid": 1,
                "module": "logs",
                "action": "getLogs",
                "address": AAVE_V3_POOL,
                "topic0": AAVE_V3_BORROW_TOPIC0,
                "fromBlock": chunk_start,
                "toBlock": chunk_end,
                "page": page,
                "offset": PAGE_SIZE,
                "apikey": apikey,
            })
            if str(data.get("status")) != "1":
                break
            result = data.get("result", [])
            if not isinstance(result, list) or not result:
                break
            for log in result:
                topics = log.get("topics", [])
                if len(topics) <= BORROW_TOPIC_INDEX:
                    continue
                w = topic_to_address(topics[BORROW_TOPIC_INDEX]).lower()
                if w not in seen:
                    seen.add(w)
                    wallets.append(w)
                    if len(wallets) >= cap:
                        return wallets
            if len(result) < PAGE_SIZE or page * PAGE_SIZE >= 10_000:
                break
            page += 1
        chunk_end = chunk_start - 1
    return wallets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=3, help="Lookback for recent borrowers")
    ap.add_argument("--limit", type=int, default=1500, help="Max distinct wallets to enumerate")
    ap.add_argument("--max-minutes", type=int, default=240, help="Wall-clock budget for scoring")
    ap.add_argument("--ttl-days", type=int, default=store.SCORE_TTL_DAYS, help="Skip wallets fresher than this")
    args = ap.parse_args()

    apikey = os.getenv("ETHERSCAN_API_KEY", "").strip()
    if not apikey:
        sys.exit("Set ETHERSCAN_API_KEY first.")
    if not store.enabled():
        sys.exit("DATABASE_URL not set (or psycopg2 missing) - nothing to write to.")

    model = load_model()
    if not model:
        sys.exit("model.json not found in repo root.")

    store.init_schema()

    start_ts = int(time.time()) - args.months * 30 * 86400
    print("Resolving block range...")
    from_block = get_block_by_time(apikey, start_ts)
    to_block = get_latest_block(apikey)
    print(f"Enumerating Aave V3 borrowers over blocks {from_block:,}-{to_block:,} (~{args.months} mo)...")
    wallets = enumerate_borrowers(apikey, from_block, to_block, args.limit)
    print(f"Found {len(wallets)} distinct recent borrowers (cap {args.limit}).")

    fresh = store.get_fresh_wallets(args.ttl_days)
    print(f"{len(fresh)} already fresh in the store; will skip those.")

    deadline = time.time() + args.max_minutes * 60
    scored = skipped = failed = 0
    for i, w in enumerate(wallets, 1):
        if time.time() > deadline:
            print(f"Time budget reached; stopping at {i - 1}/{len(wallets)}.")
            break
        if w in fresh:
            skipped += 1
            continue
        try:
            feats = live_model_features(w, apikey)
            result = score_with_model(feats, model)
            result["wallet"] = w
            result["features"] = feats
            store.upsert_score(w, result, source="batch")
            scored += 1
            if scored % 25 == 0:
                print(f"  scored {scored}  (skipped {skipped}, failed {failed})...")
        except Exception as e:
            failed += 1
            print(f"  fail {w}: {e}")

    print(f"Done. scored={scored} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()
