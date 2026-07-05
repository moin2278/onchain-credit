"""Step 1: Pull Aave V3 liquidation + borrow events from Etherscan logs.

Usage:
    export ETHERSCAN_API_KEY=your_key
    python -m backtest.pull_events --months 18 --out data/backtest

Outputs (JSONL, append-safe / resumable):
    data/backtest/liquidations.jsonl   {wallet, ts, block, tx_hash}
    data/backtest/borrowers.jsonl      {wallet, ts, block, tx_hash}

Etherscan getLogs returns max 1000 rows per call, so we walk the block
range in chunks and page within each chunk. Free-tier throttling is
inherited from api/etherscan.py.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Set

from api.etherscan import etherscan_v2_call
from backtest import EVENT_CONFIGS, topic_to_address

BLOCKS_PER_CHUNK = 40_000  # ~5.5 days of mainnet blocks
PAGE_SIZE = 1000


def get_block_by_time(apikey: str, ts: int) -> int:
    data = etherscan_v2_call({
        "chainid": 1,
        "module": "block",
        "action": "getblocknobytime",
        "timestamp": ts,
        "closest": "before",
        "apikey": apikey,
    })
    if str(data.get("status")) != "1":
        raise RuntimeError(f"getblocknobytime failed: {data}")
    return int(data["result"])


def get_latest_block(apikey: str) -> int:
    # eth_blockNumber via proxy module (no status field; result is hex)
    data = etherscan_v2_call({
        "chainid": 1,
        "module": "proxy",
        "action": "eth_blockNumber",
        "apikey": apikey,
    })
    result = data.get("result")
    if isinstance(result, str) and result.startswith("0x"):
        return int(result, 16)
    raise RuntimeError(f"eth_blockNumber failed: {data}")


def pull_logs(
    apikey: str,
    address: str,
    topic0: str,
    from_block: int,
    to_block: int,
    borrower_topic_index: int,
    out_path: Path,
    seen: Set[str],
) -> int:
    """Walk block range in chunks, page within chunks, append rows to JSONL."""
    written = 0
    chunk_start = from_block

    with open(out_path, "a") as out:
        while chunk_start <= to_block:
            chunk_end = min(chunk_start + BLOCKS_PER_CHUNK - 1, to_block)

            page = 1
            while True:
                data = etherscan_v2_call({
                    "chainid": 1,
                    "module": "logs",
                    "action": "getLogs",
                    "address": address,
                    "topic0": topic0,
                    "fromBlock": chunk_start,
                    "toBlock": chunk_end,
                    "page": page,
                    "offset": PAGE_SIZE,
                    "apikey": apikey,
                })

                status = str(data.get("status"))
                result = data.get("result", [])

                # "No records found" comes back as status=0
                if status != "1":
                    msg = str(data.get("message", "")).lower()
                    if "no records" in msg or result == []:
                        break
                    raise RuntimeError(f"getLogs failed: {data}")

                if not isinstance(result, list) or not result:
                    break

                for log in result:
                    topics = log.get("topics", [])
                    if len(topics) <= borrower_topic_index:
                        continue
                    row = {
                        "wallet": topic_to_address(topics[borrower_topic_index]),
                        "ts": int(log["timeStamp"], 16),
                        "block": int(log["blockNumber"], 16),
                        "tx_hash": log.get("transactionHash", ""),
                    }
                    key = f"{row['tx_hash']}:{row['wallet']}"
                    if key in seen:
                        continue
                    seen.add(key)
                    out.write(json.dumps(row) + "\n")
                    written += 1
                out.flush()

                if len(result) < PAGE_SIZE:
                    break
                page += 1
                if page * PAGE_SIZE > 10_000:
                    # Etherscan page*offset cap inside one chunk; halve chunk
                    # size on rerun if you ever hit this on a busy range.
                    print(f"  WARNING: >10k logs in blocks {chunk_start}-{chunk_end}; "
                          f"some skipped. Re-run this range with smaller chunks.",
                          file=sys.stderr)
                    break

            pct = 100 * (chunk_end - from_block + 1) / max(1, to_block - from_block + 1)
            print(f"  blocks {chunk_start:,}-{chunk_end:,}  ({pct:5.1f}%)  rows so far: {written}")
            chunk_start = chunk_end + 1

    return written


def load_seen(path: Path) -> Set[str]:
    seen = set()
    if path.exists():
        for line in open(path):
            try:
                r = json.loads(line)
                seen.add(f"{r['tx_hash']}:{r['wallet']}")
            except Exception:
                continue
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=18, help="Lookback window in months")
    ap.add_argument("--out", default="data/backtest", help="Output directory")
    ap.add_argument("--protocol", default="aave_v3", choices=list(EVENT_CONFIGS))
    args = ap.parse_args()

    apikey = os.getenv("ETHERSCAN_API_KEY", "").strip()
    if not apikey:
        sys.exit("Set ETHERSCAN_API_KEY first.")

    cfg = EVENT_CONFIGS[args.protocol]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    start_ts = int(time.time()) - args.months * 30 * 86400
    print("Resolving block range...")
    from_block = get_block_by_time(apikey, start_ts)
    to_block = get_latest_block(apikey)
    print(f"Blocks {from_block:,} -> {to_block:,} (~{args.months} months)")

    liq_path = out_dir / "liquidations.jsonl"
    bor_path = out_dir / "borrowers.jsonl"

    print(f"\n[1/2] Pulling LiquidationCall events from {cfg['pool']}...")
    n = pull_logs(apikey, cfg["pool"], cfg["liquidation_topic0"],
                  from_block, to_block, cfg["liquidation_borrower_topic_index"],
                  liq_path, load_seen(liq_path))
    print(f"  -> {n} new liquidation rows -> {liq_path}")

    print(f"\n[2/2] Pulling Borrow events (control-group pool)...")
    n = pull_logs(apikey, cfg["pool"], cfg["borrow_topic0"],
                  from_block, to_block, cfg["borrow_borrower_topic_index"],
                  bor_path, load_seen(bor_path))
    print(f"  -> {n} new borrow rows -> {bor_path}")

    print("\nDone. Next: python -m backtest.build_dataset")


if __name__ == "__main__":
    main()
