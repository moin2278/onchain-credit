from fastapi import FastAPI, Query
from typing import Any, Dict, List, Optional, Tuple
import os
import time
import math
import requests
from datetime import datetime, timezone

app = FastAPI()

# =========================
# Config
# =========================
ETHERSCAN_V2_BASE = "https://api.etherscan.io/v2/api"
CHAIN_ID_ETH = 1

DEFAULT_TIMEOUT = 20

# Etherscan constraint: page * offset <= 10000
PAGE_SIZE = 1000
MAX_PAGES = 10  # 10 * 1000 = 10,000 max rows

# Free-tier safe throttling (tune if you have higher plan)
# If you hit "3/sec", use >= 0.40 sec.
MIN_SECONDS_BETWEEN_CALLS = 0.40

# Retry/backoff
MAX_RETRIES = 6
BACKOFF_BASE_SECONDS = 0.8

# Stablecoin symbols (best-effort)
STABLE_SYMBOLS = {
    "USDC", "USDT", "DAI", "TUSD", "USDP", "FDUSD", "FRAX", "LUSD", "GUSD"
}

# Simple in-memory cache (optional)
_CACHE: Dict[str, Dict[str, Any]] = {}

def cache_get(key: str) -> Optional[Dict[str, Any]]:
    hit = _CACHE.get(key)
    if not hit:
        return None
    if time.time() > hit["expires_at"]:
        _CACHE.pop(key, None)
        return None
    return hit["value"]

def cache_set(key: str, value: Dict[str, Any], ttl_sec: int = 300) -> None:
    _CACHE[key] = {"value": value, "expires_at": time.time() + ttl_sec}


# =========================
# Throttle helper (global)
# =========================
_LAST_CALL_AT = 0.0

def _throttle_wait() -> None:
    global _LAST_CALL_AT
    now = time.time()
    elapsed = now - _LAST_CALL_AT
    if elapsed < MIN_SECONDS_BETWEEN_CALLS:
        time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)
    _LAST_CALL_AT = time.time()


# =========================
# Etherscan helpers
# =========================
def etherscan_v2_call(params: Dict[str, Any], timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """
    One Etherscan V2 call with:
      - global throttling
      - retry with exponential backoff when rate-limited / NOTOK
    """
    last_err = None

    for attempt in range(1, MAX_RETRIES + 1):
        _throttle_wait()

        try:
            r = requests.get(ETHERSCAN_V2_BASE, params=params, timeout=timeout)
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
        except Exception as e:
            last_err = f"request_exception: {e}"
            data = None

        # If we couldn't parse JSON, retry
        if not isinstance(data, dict):
            sleep_s = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            time.sleep(sleep_s)
            continue

        status = str(data.get("status", ""))
        message = str(data.get("message", ""))
        result = data.get("result")

        # Success
        if status == "1" and message.upper() == "OK":
            return data

        # Rate limit / NOTOK cases
        result_str = str(result) if result is not None else ""
        combined = f"{message} {result_str}".lower()

        is_rate_limit = ("rate limit" in combined) or ("max calls per sec" in combined)
        if is_rate_limit:
            sleep_s = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            time.sleep(sleep_s)
            last_err = f"rate_limited: {message} / {result_str}"
            continue

        # Other NOTOK (invalid key, etc.) -> return immediately (no point retrying forever)
        return data

    # If all retries failed, return a NOTOK-like object
    return {"status": "0", "message": "NOTOK", "result": f"Retries exhausted. Last error: {last_err}"}


def _filter_by_ts(rows: List[Dict[str, Any]], start_ts: int, end_ts: int) -> List[Dict[str, Any]]:
    """
    Keep items with timeStamp between [start_ts, end_ts].
    Etherscan returns timeStamp as string.
    """
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
    """
    Fetch txs for a given action using paging within Etherscan constraints.
    Returns: (items_in_window, error_message, truncated)

    NOTE:
      - We page and filter by timestamp locally.
      - Early stop: if sort=desc and we already see rows older than start_ts, we can stop paging.
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
            # NOTOK: return error
            msg = f"Etherscan error: status={data.get('status')}, message={data.get('message')}, result={data.get('result')}"
            return [], msg, False

        rows = data.get("result", [])
        if not isinstance(rows, list):
            return [], f"Unexpected result type for {action}: {type(rows)}", False

        if not rows:
            break

        # Filter to window
        win_rows = _filter_by_ts(rows, start_ts, end_ts)
        all_rows.extend(win_rows)

        # Early stop when descending and we saw anything older than start_ts
        if sort == "desc":
            # Find minimum ts in this page
            try:
                min_ts = min(int(x.get("timeStamp", "0")) for x in rows)
            except Exception:
                min_ts = None
            if min_ts is not None and min_ts < start_ts:
                break

        # If we keep getting full pages, there may be more
        if len(rows) < PAGE_SIZE:
            break

        if page == MAX_PAGES:
            truncated = True

    return all_rows, None, truncated


def get_wallet_first_seen_ts(apikey: str, wallet: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Gets earliest-ever normal tx timestamp using txlist sort=asc, offset=1.
    This avoids wallet_age_days becoming 0 for empty 30d windows.
    """
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


# =========================
# Feature computation
# =========================
def compute_features(wallet: str, window_days: int, offset_days: int, apikey: str) -> Dict[str, Any]:
    now_ts = int(time.time())
    end_ts = now_ts - (offset_days * 86400)
    start_ts = end_ts - (window_days * 86400)

    errors: Dict[str, str] = {}
    risk_flags: List[Dict[str, Any]] = []
    truncated_any = False

    # Fetch 3 buckets (in-window)
    normal, err, trunc = fetch_action_desc(apikey, wallet, "txlist", start_ts, end_ts)
    if err:
        errors["normal"] = err
    truncated_any = truncated_any or trunc

    internal, err, trunc = fetch_action_desc(apikey, wallet, "txlistinternal", start_ts, end_ts)
    if err:
        errors["internal"] = err
    truncated_any = truncated_any or trunc

    erc20, err, trunc = fetch_action_desc(apikey, wallet, "tokentx", start_ts, end_ts)
    if err:
        errors["erc20"] = err
    truncated_any = truncated_any or trunc

    data_ok = (len(errors) == 0)

    normal_count = len(normal) if "normal" not in errors else 0
    internal_count = len(internal) if "internal" not in errors else 0
    erc20_count = len(erc20) if "erc20" not in errors else 0

    # wallet_age_days from FIRST EVER tx (not just window)
    wallet_age_days = 0
    first_seen_ts, age_err = get_wallet_first_seen_ts(apikey, wallet)
    if age_err:
        # not fatal, but record it
        errors["age"] = age_err
        data_ok = False
    if first_seen_ts:
        wallet_age_days = max(0, (now_ts - first_seen_ts) // 86400)

    # Consistency: unique active days / window_days (based on any tx type within window)
    active_days = set()
    for x in (normal + internal + erc20):
        try:
            ts = int(x.get("timeStamp", "0"))
        except Exception:
            continue
        day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        active_days.add(day)

    consistency_score = round(len(active_days) / max(1, window_days), 4)

    # Unique tokens + counterparties from ERC20
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

        # counterparties = other side of transfer relative to wallet
        if frm == w and to:
            counterparties.add(to)
        elif to == w and frm:
            counterparties.add(frm)

        if sym in STABLE_SYMBOLS:
            stable_count += 1

    unique_tokens_n = len(unique_tokens)
    unique_counterparties_n = len(counterparties)
    stablecoin_ratio = round(stable_count / max(1, erc20_count), 4) if erc20_count else 0.0

    # Risk flags based on window activity
    if (normal_count + internal_count) == 0:
        risk_flags.append({
            "flag": "no_eth_activity_in_window",
            "severity": "medium",
            "note": f"No normal/internal tx activity in last {window_days} days"
        })

    if erc20_count == 0:
        risk_flags.append({
            "flag": "no_erc20_activity_in_window",
            "severity": "high",
            "note": f"No ERC-20 activity in last {window_days} days"
        })

    if truncated_any:
        risk_flags.append({
            "flag": "history_truncated",
            "severity": "medium",
            "note": "Wallet has more activity than fetched (hit paging limits). Features may be partial."
        })

    # Simple score (adjust as you like)
    score = 10
    score += min(10, len(active_days))  # up to +10
    score += min(6, unique_tokens_n // 10)  # small bump for diversity

    if erc20_count == 0:
        score -= 12
    if (normal_count + internal_count) == 0:
        score -= 6
    if truncated_any:
        score -= 2

    # Risk tier mapping (THIS is what makes inactive wallets "HIGH")
    if not data_ok:
        risk_tier = "UNKNOWN"
    else:
        if score <= 0:
            risk_tier = "HIGH"
        elif score <= 6:
            risk_tier = "MEDIUM"
        else:
            risk_tier = "LOW"

    return {
        "wallet": wallet,
        "window_days": window_days,
        "offset_days": offset_days,
        "data_ok": data_ok,
        "errors": errors,
        "wallet_age_days": int(wallet_age_days),
        "consistency_score": float(consistency_score),
        "unique_tokens": int(unique_tokens_n),
        "unique_counterparties": int(unique_counterparties_n),
        "stablecoin_ratio": float(stablecoin_ratio),
        "normal_tx_count": int(normal_count),
        "internal_tx_count": int(internal_count),
        "erc20_tx_count": int(erc20_count),
        "score": int(score),
        "risk_tier": risk_tier,
        "risk_flags": risk_flags,
    }


def compute_trajectory(curr: Dict[str, Any], prev: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "consistency_score",
        "unique_tokens",
        "unique_counterparties",
        "stablecoin_ratio",
        "normal_tx_count",
        "internal_tx_count",
        "erc20_tx_count",
        "score",
    ]
    deltas = {k: float(curr.get(k, 0)) - float(prev.get(k, 0)) for k in keys}

    # Direction heuristic
    risk_dir = "flat"
    if deltas["score"] > 0:
        risk_dir = "improving"
    elif deltas["score"] < 0:
        risk_dir = "worsening"

    return {"deltas": deltas, "direction": {"risk": risk_dir}}


# =========================
# API Endpoints
# =========================
@app.get("/features")
def features(
    wallet: str = Query(...),
    profile: str = Query("aave"),
    window_days: int = Query(30),
    offset_days: int = Query(0),
):
    # Read key from env
    apikey = os.getenv("ETHERSCAN_API_KEY", "").strip()

    cache_key = f"features:{wallet}:{profile}:{window_days}:{offset_days}"
    cached = cache_get(cache_key)
    if cached:
        cached["cached"] = True
        cached["_cached_at"] = int(time.time())
        return {"wallet": wallet, "profile": profile, "features": cached}

    feats = compute_features(wallet, window_days, offset_days, apikey)
    feats["cached"] = False
    feats["_cached_at"] = int(time.time())

    cache_set(cache_key, feats, ttl_sec=300)
    return {"wallet": wallet, "profile": profile, "features": feats}


@app.get("/trajectory")
def trajectory(
    wallet: str = Query(...),
    profile: str = Query("aave"),
    window_days: int = Query(30),
):
    apikey = os.getenv("ETHERSCAN_API_KEY", "").strip()

    curr = compute_features(wallet, window_days, 0, apikey)
    prev = compute_features(wallet, window_days, window_days, apikey)

    traj = {
        "wallet_age_days": curr.get("wallet_age_days", 0),
        "current": curr,
        "previous": prev,
        **compute_trajectory(curr, prev),
    }
    return {"wallet": wallet, "profile": profile, "trajectory": traj}