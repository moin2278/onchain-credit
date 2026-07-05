"""Live scoring with the trained backtest model (model.json).

This is the validated model from backtest/train_model.py - NOT the v1
heuristic. It reproduces the exact feature construction used in training:
  - behavioral features from the last 30 days (api/features.py)
  - Aave V3 borrowing-history features fetched live via a single
    filtered getLogs call (topic0 = Borrow, topic2 = wallet)
then applies the standardizer + logistic coefficients from model.json.

model.json must sit in the repo root (copy your trained
data/backtest/model.json there and commit it).
"""

import json
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.etherscan import etherscan_v2_call
from backtest import AAVE_V3_BORROW_TOPIC0, AAVE_V3_POOL
from backtest.protocol_features import protocol_features

MODEL_PATH = Path(__file__).resolve().parent.parent / "model.json"

_MODEL_CACHE: Optional[Dict[str, Any]] = None


def load_model() -> Optional[Dict[str, Any]]:
    global _MODEL_CACHE
    if _MODEL_CACHE is None and MODEL_PATH.exists():
        _MODEL_CACHE = json.load(open(MODEL_PATH))
    return _MODEL_CACHE


def _pad_topic_address(wallet: str) -> str:
    return "0x" + "0" * 24 + wallet.lower().replace("0x", "")


def fetch_wallet_aave_borrow_ts(apikey: str, wallet: str) -> List[int]:
    """All Aave V3 Borrow events where onBehalfOf == wallet (one log query)."""
    ts: List[int] = []
    page = 1
    while True:
        data = etherscan_v2_call({
            "chainid": 1,
            "module": "logs",
            "action": "getLogs",
            "address": AAVE_V3_POOL,
            "topic0": AAVE_V3_BORROW_TOPIC0,
            "topic2": _pad_topic_address(wallet),
            "topic0_2_opr": "and",
            "fromBlock": 0,
            "toBlock": "latest",
            "page": page,
            "offset": 1000,
            "apikey": apikey,
        })
        result = data.get("result", [])
        if str(data.get("status")) != "1" or not isinstance(result, list) or not result:
            break
        ts.extend(int(l["timeStamp"], 16) for l in result if "timeStamp" in l)
        if len(result) < 1000 or page * 1000 >= 10_000:
            break
        page += 1
    return sorted(ts)


# Feature construction MUST mirror backtest/train_model.py exactly.
def build_feature_vector(feats: Dict[str, Any], names: List[str]) -> List[float]:
    log1p = lambda v: math.log1p(max(0.0, float(v)))
    fmap = {
        "log_wallet_age": lambda: log1p(feats.get("wallet_age_days", 0)),
        "log_total_tx": lambda: log1p(feats.get("total_tx", 0)),
        "log_erc20_tx": lambda: log1p(feats.get("erc20_tx_count", 0)),
        "log_unique_tokens": lambda: log1p(feats.get("unique_tokens", 0)),
        "log_counterparties": lambda: log1p(feats.get("unique_counterparties", 0)),
        "consistency": lambda: float(feats.get("consistency_score", 0)),
        "stablecoin_ratio": lambda: float(feats.get("stablecoin_ratio", 0)),
        "dormant_pre_window": lambda: 1.0 if feats.get("total_tx", 0) == 0 else 0.0,
        "log_prior_borrows": lambda: log1p(feats.get("prior_borrow_count", 0)),
        "borrows_per_month": lambda: float(feats.get("borrows_per_month", 0)),
        "log_days_since_borrow": lambda: log1p(max(0, feats.get("days_since_last_borrow", -1))),
        "never_borrowed_before": lambda: 1.0 if feats.get("days_since_last_borrow", -1) < 0 else 0.0,
        "recent_borrow_burst": lambda: float(feats.get("recent_borrow_burst", 0)),
    }
    return [fmap[n]() for n in names]


def score_with_model(feats: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, Any]:
    """Standardize, apply logistic model, tier by trained cutoffs, explain."""
    names = model["feature_names"]
    x = build_feature_vector(feats, names)
    z = [(v - m) / (s if s else 1.0)
         for v, m, s in zip(x, model["scaler_mean"], model["scaler_scale"])]
    contribs = [zi * c for zi, c in zip(z, model["coefficients"])]
    logit = model["intercept"] + sum(contribs)
    p = 1.0 / (1.0 + math.exp(-logit))

    cuts = model["tier_cutoffs"]
    if p >= cuts["high_min_p"]:
        tier = "HIGH"
    elif p <= cuts["low_max_p"]:
        tier = "LOW"
    else:
        tier = "MEDIUM"

    drivers = sorted(
        ({"feature": n, "contribution": round(c, 3),
          "direction": "raises risk" if c > 0 else "lowers risk"}
         for n, c in zip(names, contribs) if abs(c) > 0.01),
        key=lambda d: -abs(d["contribution"]),
    )[:6]

    return {
        "risk_probability": round(p, 4),
        "risk_tier": tier,
        "drivers": drivers,
        "model": {
            "type": "logistic_regression",
            "cv_auc": model.get("cv_auc_mean"),
            "trained_on_rows": model.get("n_rows"),
            "task": "P(liquidated within 90 days | borrow now)",
        },
    }


def live_model_features(wallet: str, apikey: str) -> Dict[str, Any]:
    """Behavioral (last 30d) + live Aave borrow-history features, as of now."""
    from api.features import compute_features  # local import avoids cycles

    now_ts = int(time.time())
    feats = compute_features(wallet, 30, 0, apikey)
    borrow_ts = fetch_wallet_aave_borrow_ts(apikey, wallet)
    feats.update(protocol_features(wallet, now_ts, {wallet.lower(): borrow_ts}))
    feats["aave_borrow_events_found"] = len(borrow_ts)
    return feats
