"""On-Chain Credit Risk Scoring API.

Endpoints:
  GET /health      - liveness + config check
  GET /features    - ML-ready wallet features
  GET /score       - risk score, tier, flags, credit decision, LTV/APR rec
  GET /compare     - score two wallets side by side
  GET /trajectory  - current vs previous window, with drivers

Note: cache and Etherscan throttle are in-memory and per-process.
Run single-worker (default Procfile) or swap in Redis before scaling out.
"""

import os
import re
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse

from api.features import compute_features
from api.model_scoring import live_model_features, load_model, score_with_model
from api.scoring import PROFILES, credit_decision, score_wallet
from api.trajectory import compute_trajectory

app = FastAPI(
    title="On-Chain Credit Risk Scoring API",
    description="Explainable wallet risk + credit decisioning for DeFi lending.",
    version="1.1.0",
)

ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

# Simple in-memory cache (per-process)
_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SEC = 300


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    hit = _CACHE.get(key)
    if not hit:
        return None
    if time.time() > hit["expires_at"]:
        _CACHE.pop(key, None)
        return None
    return hit["value"]


def _cache_set(key: str, value: Dict[str, Any]) -> None:
    _CACHE[key] = {"value": value, "expires_at": time.time() + CACHE_TTL_SEC}


# Per-IP rate limit for expensive scoring endpoints (in-memory, per-process)
_RATE: Dict[str, list] = {}
RATE_LIMIT_PER_HOUR = 20


def _check_rate_limit(request: Request) -> None:
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else "unknown"))
    now = time.time()
    hits = [t for t in _RATE.get(ip, []) if now - t < 3600]
    if len(hits) >= RATE_LIMIT_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit reached ({RATE_LIMIT_PER_HOUR} scores/hour). "
                   "Try again later or run the open-source pipeline locally.",
        )
    hits.append(now)
    _RATE[ip] = hits


def _require_wallet(wallet: str) -> str:
    if not ADDRESS_RE.match(wallet or ""):
        raise HTTPException(status_code=422, detail=f"Invalid Ethereum address: {wallet}")
    return wallet.lower()


def _apikey() -> str:
    key = os.getenv("ETHERSCAN_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail="ETHERSCAN_API_KEY is not configured on the server.",
        )
    return key


def _features_cached(wallet: str, window_days: int, offset_days: int, apikey: str) -> Dict[str, Any]:
    cache_key = f"features:{wallet}:{window_days}:{offset_days}"
    cached = _cache_get(cache_key)
    if cached:
        out = dict(cached)
        out["cached"] = True
        return out
    feats = compute_features(wallet, window_days, offset_days, apikey)
    feats["cached"] = False
    _cache_set(cache_key, feats)
    return feats


WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


@app.get("/", include_in_schema=False)
def home():
    index = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Site not built")


@app.get("/score_model")
def score_model(
    request: Request,
    wallet: str = Query(..., description="0x-prefixed Ethereum address"),
):
    """Score with the TRAINED model from the published backtest (model.json)."""
    model = load_model()
    if not model:
        raise HTTPException(status_code=503,
                            detail="model.json not deployed on this server.")
    _check_rate_limit(request)
    w = _require_wallet(wallet)
    feats = live_model_features(w, _apikey())
    result = score_with_model(feats, model)
    result["wallet"] = w
    result["features"] = feats
    return result


@app.get("/health")
def health():
    return {
        "status": "ok",
        "etherscan_key_configured": bool(os.getenv("ETHERSCAN_API_KEY", "").strip()),
        "profiles": sorted(PROFILES.keys()),
    }


@app.get("/features")
def features(
    wallet: str = Query(..., description="0x-prefixed Ethereum address"),
    window_days: int = Query(30, ge=1, le=365),
    offset_days: int = Query(0, ge=0, le=365),
):
    wallet = _require_wallet(wallet)
    feats = _features_cached(wallet, window_days, offset_days, _apikey())
    return {"wallet": wallet, "features": feats}


@app.get("/score")
def score(
    wallet: str = Query(..., description="0x-prefixed Ethereum address"),
    profile: str = Query("aave", description=f"One of: {sorted(PROFILES.keys())}"),
    window_days: int = Query(30, ge=1, le=365),
):
    wallet = _require_wallet(wallet)
    feats = _features_cached(wallet, window_days, 0, _apikey())
    scored = score_wallet(feats)
    decision = credit_decision(scored, profile=profile)
    return {
        "wallet": wallet,
        "profile": decision["profile"],
        "score": scored["score"],
        "risk_tier": scored["risk_tier"],
        "decision": decision["decision"],
        "recommendation": decision["recommendation"],
        "reasons": decision["reasons"],
        "explainability": {
            "breakdown": scored["breakdown"],
            "penalties": scored["penalties"],
        },
        "risk_flags": scored["risk_flags"],
        "features": feats,
    }


@app.get("/compare")
def compare(
    walletA: str = Query(...),
    walletB: str = Query(...),
    profile: str = Query("aave"),
    window_days: int = Query(30, ge=1, le=365),
):
    a = _require_wallet(walletA)
    b = _require_wallet(walletB)
    apikey = _apikey()

    results = {}
    for label, w in (("walletA", a), ("walletB", b)):
        feats = _features_cached(w, window_days, 0, apikey)
        scored = score_wallet(feats)
        decision = credit_decision(scored, profile=profile)
        results[label] = {
            "wallet": w,
            "score": scored["score"],
            "risk_tier": scored["risk_tier"],
            "decision": decision["decision"],
            "recommendation": decision["recommendation"],
            "risk_flags": [f["flag"] for f in scored["risk_flags"]],
        }

    sa, sb = results["walletA"]["score"], results["walletB"]["score"]
    if sa > sb:
        lower_risk = a
    elif sb > sa:
        lower_risk = b
    else:
        lower_risk = None

    return {
        "profile": profile,
        "comparison": results,
        "lower_risk_wallet": lower_risk,
    }


@app.get("/trajectory")
def trajectory(
    wallet: str = Query(...),
    window_days: int = Query(30, ge=1, le=180),
):
    wallet = _require_wallet(wallet)
    apikey = _apikey()

    curr = _features_cached(wallet, window_days, 0, apikey)
    prev = _features_cached(wallet, window_days, window_days, apikey)

    traj = compute_trajectory(curr, prev)
    return {
        "wallet": wallet,
        "window_days": window_days,
        "wallet_age_days": curr.get("wallet_age_days", 0),
        "trajectory": traj,
        "current": curr,
        "previous": prev,
    }
