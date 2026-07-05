"""Etherscan V2 ingestion client.

Rate-limit-safe access to Etherscan's account endpoints:
  - global throttling (free-tier safe)
  - retry with exponential backoff on rate limits
  - pagination within Etherscan's page * offset <= 10,000 constraint
  - local timestamp-window filtering with early stop
"""

import time
from typing import Any, Dict, List, Optional, Tuple

import requests

ETHERSCAN_V2_BASE = "https://api.etherscan.io/v2/api"
CHAIN_ID_ETH = 1

DEFAULT_TIMEOUT = 20

# Etherscan constraint: page * offset <= 10000
PAGE_SIZE = 1000
MAX_PAGES = 10  # 10 * 1000 = 10,000 max rows

# Free-tier safe throttling (tune if you have a higher plan)
MIN_SECONDS_BETWEEN_CALLS = 0.40

# Retry/backoff
MAX_RETRIES = 6
BACKOFF_BASE_SECONDS = 0.8

_LAST_CALL_AT = 0.0


def _throttle_wait() -> None:
    """Global throttle across all Etherscan calls (single-process only)."""
    global _LAST_CALL_AT
    now = time.time()
    elapsed = now - _LAST_CALL_AT
    if elapsed < MIN_SECONDS_BETWEEN_CALLS:
        time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)
    _LAST_CALL_AT = time.time()


def etherscan_v2_call(params: Dict[str, Any], timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """One Etherscan V2 call with throttling and retry/backoff on rate limits."""
    last_err = None

    for attempt in range(1, MAX_RETRIES + 1):
        _throttle_wait()

        try:
            r = requests.get(ETHERSCAN_V2_BASE, params=params, timeout=timeout)
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
        except Exception as e:
            last_err = f"request_exception: {e}"
            data = None

        if not isinstance(data, dict):
            time.sleep(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
            continue

        status = str(data.get("status", ""))
        message = str(data.get("message", ""))
        result = data.get("result")

        if status == "1" and message.upper() == "OK":
            return data

        result_str = str(result) if result is not None else ""
        combined = f"{message} {result_str}".lower()

        is_rate_limit = ("rate limit" in combined) or ("max calls per sec" in combined)
        if is_rate_limit:
            time.sleep(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
            last_err = f"rate_limited: {message} / {result_str}"
            continue

        # Other NOTOK (invalid key, bad address, etc.) -> return immediately
        return data

    return {"status": "0", "message": "NOTOK", "result": f"Retries exhausted. Last error: {last_err}"}


def filter_by_ts(rows: List[Dict[str, Any]], start_ts: int, end_ts: int) -> List[Dict[str, Any]]:
    """Keep rows whose timeStamp falls within [start_ts, end_ts]."""
    out = []
    for x in rows:
        ts = x.get("timeStamp")
        if ts is None:
            continue
        try:
            ts_i = int(ts)
        except Exception:
            continue
        if start_ts <= ts_i <= end_ts:
            out.append(x)
    return out


def fetch_action_desc(
    apikey: str,
    wallet: str,
    action: str,
    start_ts: int,
    end_ts: int,
    sort: str = "desc",
) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
    """Fetch txs for an action, paging within Etherscan constraints.

    Returns: (items_in_window, error_message, truncated)
    """
    if not apikey:
        return [], "Missing Etherscan API key (export ETHERSCAN_API_KEY=...)", False

    all_rows: List[Dict[str, Any]] = []
    truncated = False

    for page in range(1, MAX_PAGES + 1):
        params = {
            "chainid": CHAIN_ID_ETH,
            "module": "account",
            "action": action,
            "address": wallet,
            "page": page,
            "offset": PAGE_SIZE,
            "sort": sort,
            "apikey": apikey,
        }

        data = etherscan_v2_call(params)

        if str(data.get("status")) != "1":
            msg = (
                f"Etherscan error: status={data.get('status')}, "
                f"message={data.get('message')}, result={data.get('result')}"
            )
            return [], msg, False

        rows = data.get("result", [])
        if not isinstance(rows, list):
            return [], f"Unexpected result type for {action}: {type(rows)}", False

        if not rows:
            break

        all_rows.extend(filter_by_ts(rows, start_ts, end_ts))

        # Early stop when descending and we already paged past the window start
        if sort == "desc":
            try:
                min_ts = min(int(x.get("timeStamp", "0")) for x in rows)
            except Exception:
                min_ts = None
            if min_ts is not None and min_ts < start_ts:
                break

        if len(rows) < PAGE_SIZE:
            break

        if page == MAX_PAGES:
            truncated = True

    return all_rows, None, truncated


def get_wallet_first_seen_ts(apikey: str, wallet: str) -> Tuple[Optional[int], Optional[str]]:
    """Earliest-ever normal tx timestamp (txlist, sort=asc, offset=1)."""
    if not apikey:
        return None, "Missing Etherscan API key"

    params = {
        "chainid": CHAIN_ID_ETH,
        "module": "account",
        "action": "txlist",
        "address": wallet,
        "page": 1,
        "offset": 1,
        "sort": "asc",
        "apikey": apikey,
    }
    data = etherscan_v2_call(params)
    if str(data.get("status")) != "1":
        return None, f"Etherscan error: {data.get('message')} / {data.get('result')}"

    rows = data.get("result", [])
    if not isinstance(rows, list) or not rows:
        return None, None

    try:
        return int(rows[0]["timeStamp"]), None
    except Exception:
        return None, None
