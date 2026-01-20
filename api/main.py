import re
from typing import Dict, Any, Tuple
from time import time as now
from fastapi import FastAPI, HTTPException
from datetime import datetime
import requests
import pandas as pd

app = FastAPI(title="On-Chain Credit Scoring API")

# -------------------------
# Wallet Validation
# -------------------------
WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

def validate_wallet(wallet: str) -> str:
    wallet = wallet.strip()
    if not WALLET_RE.match(wallet):
        raise HTTPException(
            status_code=400,
            detail="Invalid wallet address format"
        )
    return wallet

# -------------------------
# In-Memory Cache
# -------------------------
CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 5  # TEMP: 5 seconds for testing

def cache_get(key: str):
    item = CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if now() - ts > CACHE_TTL_SECONDS:
        CACHE.pop(key, None)
        return None
    return value

def cache_set(key: str, value: Dict[str, Any]):
    CACHE[key] = (now(), value)



ETHERSCAN_API_KEY = "HBVI4CYSPKQWC8ZUTTFKTBNPDST6N3IZTW"

# -------------------------
# Token Classification
# -------------------------
STABLECOINS = {
    "USDC", "USDT", "DAI", "FRAX", "TUSD", "USDP",
    "GUSD", "LUSD", "USDD", "USDE", "FDUSD", "PYUSD"
}


# -------------------------
# Data Fetching (Etherscan V2)
# -------------------------
def fetch_erc20_transfers(wallet):
    url = "https://api.etherscan.io/v2/api"
    params = {
        "chainid": 1,
        "module": "account",
        "action": "tokentx",
        "address": wallet,
        "startblock": 0,
        "endblock": 99999999,
        "sort": "asc",
        "apikey": ETHERSCAN_API_KEY
    }

    # small retry loop (2 tries)
    for attempt in range(2):
        try:
            r = requests.get(url, params=params, timeout=15)
            data = r.json()
            return data.get("result", [])
        except Exception:
            if attempt == 1:
                return []

def fetch_normal_txs(wallet):
    url = "https://api.etherscan.io/v2/api"
    params = {
        "chainid": 1,
        "module": "account",
        "action": "txlist",
        "address": wallet,
        "startblock": 0,
        "endblock": 99999999,
        "sort": "asc",
        "apikey": ETHERSCAN_API_KEY
    }

    for attempt in range(2):
        try:
            r = requests.get(url, params=params, timeout=15)
            data = r.json()
            return data.get("result", [])
        except Exception:
            if attempt == 1:
                return []

def fetch_internal_txs(wallet):
    url = "https://api.etherscan.io/v2/api"
    params = {
        "chainid": 1,
        "module": "account",
        "action": "txlistinternal",
        "address": wallet,
        "startblock": 0,
        "endblock": 99999999,
        "sort": "asc",
        "apikey": ETHERSCAN_API_KEY
    }

    for attempt in range(2):
        try:
            r = requests.get(url, params=params, timeout=15)
            data = r.json()
            return data.get("result", [])
        except Exception:
            if attempt == 1:
                return []



# -------------------------
# Feature Engineering
# -------------------------
def wallet_age_days_from_erc20(transfers):
    if not transfers:
        return 0
    first_ts = int(transfers[0]["timeStamp"])
    return (datetime.utcnow() - datetime.utcfromtimestamp(first_ts)).days

def activity_consistency(transfers):
    if not transfers:
        return 0
    df = pd.DataFrame(transfers)
    df["timeStamp"] = pd.to_datetime(df["timeStamp"].astype(int), unit="s")
    weekly = df.set_index("timeStamp").resample("W").size()
    return weekly.std() / weekly.mean() if weekly.mean() > 0 else 0

def token_diversity(transfers):
    return len({tx["tokenSymbol"] for tx in transfers if tx.get("tokenSymbol")})

def unique_counterparties(transfers, wallet):
    wallet = wallet.lower()
    counterparties = set()

    for tx in transfers:
        frm = (tx.get("from") or "").lower()
        to = (tx.get("to") or "").lower()

        if frm and frm != wallet:
            counterparties.add(frm)
        if to and to != wallet:
            counterparties.add(to)

    return len(counterparties)


def stablecoin_ratio(transfers):
    if not transfers:
        return 0.0

    stable = 0
    total = 0

    for tx in transfers:
        sym = (tx.get("tokenSymbol") or "").upper()
        if not sym:
            continue
        total += 1
        if sym in STABLECOINS:
            stable += 1

    return stable / total if total > 0 else 0.0


# -------------------------
# Credit Logic (FINAL)
# -------------------------
def risk_score(wallet_age_days, consistency, token_count, counterparty_count, stable_ratio, normal_tx_count, internal_tx_count):
    
    if wallet_age_days < 30 or token_count == 0:
        return 20

    score = 0

    # Wallet age
    if wallet_age_days > 365:
        score += 40
    elif wallet_age_days > 90:
        score += 25
    else:
        score += 10

    # Consistency (only meaningful if active)
    if token_count > 5:
        if consistency < 1:
            score += 30
        elif consistency < 2:
            score += 15
        else:
            score += 5
    else:
        score += 0

    # Token diversity
    if token_count > 10:
        score += 30
    elif token_count > 3:
        score += 15
    else:
        score += 5

    # Unique counterparties (real usage signal)
    if counterparty_count > 200:
        score += 10
    elif counterparty_count > 50:
        score += 7
    elif counterparty_count > 10:
        score += 3

    # Stablecoin ratio (finance-like behavior signal)
    if stable_ratio > 0.60:
        score += 10
    elif stable_ratio > 0.30:
        score += 5

        # Transaction activity (coverage signal)
    # Normal txs show general usage; internal txs show contract interactions
    if normal_tx_count > 200:
        score += 6
    elif normal_tx_count > 50:
        score += 3

    if internal_tx_count > 50:
        score += 6
    elif internal_tx_count > 10:
        score += 3

    return min(score, 100)

def credit_decision(wallet_age_days, token_count, score, risk_tier):
    # hard cold-start requirements
    MIN_AGE_DAYS = 30
    MIN_TOKEN_ACTIVITY = 1

    if wallet_age_days < MIN_AGE_DAYS or token_count < MIN_TOKEN_ACTIVITY:
        return {
            "status": "DENY",
            "reason": "insufficient_history",
            "min_required_age_days": MIN_AGE_DAYS,
            "min_required_token_activity": MIN_TOKEN_ACTIVITY
        }

    # policy by tier
    if risk_tier == "HIGH":
        return {"status": "DENY", "reason": "high_risk"}
    if risk_tier == "MEDIUM":
        return {"status": "LIMIT", "reason": "medium_risk"}
    return {"status": "ALLOW", "reason": "ok"}



def risk_tier(score):
    if score >= 75:
        return "LOW"
    elif score >= 45:
        return "MEDIUM"
    else:
        return "HIGH"

PROFILES = {
    "conservative": {
        "low":    {"max_ltv": 0.60, "apr": 0.09, "collateral_factor": 1.4},
        "medium": {"max_ltv": 0.45, "apr": 0.13, "collateral_factor": 1.7},
        "high":   {"max_ltv": 0.25, "apr": 0.20, "collateral_factor": 2.2},
    },
    "aave": {
        "low":    {"max_ltv": 0.65, "apr": 0.08, "collateral_factor": 1.3},
        "medium": {"max_ltv": 0.50, "apr": 0.12, "collateral_factor": 1.6},
        "high":   {"max_ltv": 0.25, "apr": 0.20, "collateral_factor": 2.2},
    },
    "morpho": {
        "low":    {"max_ltv": 0.70, "apr": 0.075, "collateral_factor": 1.25},
        "medium": {"max_ltv": 0.55, "apr": 0.11, "collateral_factor": 1.55},
        "high":   {"max_ltv": 0.30, "apr": 0.18, "collateral_factor": 2.0},
    }
}


def collateral_recommendation(
    score,
    risk_tier,
    consistency,
    stable_ratio,
    normal_tx_count,
    internal_tx_count,
    profile: str = "conservative"
):
    profile = (profile or "conservative").lower()
    if profile not in PROFILES:
        profile = "conservative"

    tier_key = "low" if risk_tier == "LOW" else "medium" if risk_tier == "MEDIUM" else "high"
    base = PROFILES[profile][tier_key]

    recommendation = {
        "profile": profile,
        "max_ltv": base["max_ltv"],
        "collateral_factor": base["collateral_factor"],
        "suggested_interest_rate_apr": base["apr"],
        "policy": tier_key,
        "rationale": [f"Base policy from '{profile}' profile ({risk_tier})"]
    }

    # Behavioral adjustments (small, explainable)
    if stable_ratio > 0.5:
        recommendation["max_ltv"] += 0.05
        recommendation["rationale"].append("High stablecoin usage (+LTV)")

    if consistency > 2:
        recommendation["max_ltv"] -= 0.05
        recommendation["rationale"].append("Highly irregular activity (-LTV)")

    if internal_tx_count > normal_tx_count:
        recommendation["max_ltv"] -= 0.05
        recommendation["rationale"].append("High contract interaction risk (-LTV)")

    recommendation["max_ltv"] = max(0.15, min(recommendation["max_ltv"], 0.75))
    return recommendation


    # --------------------
    # Risk tier driven policy
    # --------------------
    if risk_tier == "LOW":
        recommendation["max_ltv"] = 0.65
        recommendation["collateral_factor"] = 1.3
        recommendation["suggested_interest_rate_apr"] = 0.08
        recommendation["policy"] = "aggressive"
        recommendation["rationale"].append("Low risk tier")

    elif risk_tier == "MEDIUM":
        recommendation["max_ltv"] = 0.50
        recommendation["collateral_factor"] = 1.6
        recommendation["suggested_interest_rate_apr"] = 0.12
        recommendation["policy"] = "conservative"
        recommendation["rationale"].append("Medium risk tier")

    else:  # HIGH
        recommendation["max_ltv"] = 0.25
        recommendation["collateral_factor"] = 2.2
        recommendation["suggested_interest_rate_apr"] = 0.20
        recommendation["policy"] = "restrictive"
        recommendation["rationale"].append("High risk tier")

    # --------------------
    # Behavioral adjustments
    # --------------------

    # Stablecoin behavior = lower volatility
    if stable_ratio > 0.5:
        recommendation["max_ltv"] += 0.05
        recommendation["rationale"].append("High stablecoin usage")

    # Consistency penalty
    if consistency > 2:
        recommendation["max_ltv"] -= 0.05
        recommendation["rationale"].append("Highly irregular activity")

    # Heavy contract interaction = smart contract risk
    if internal_tx_count > normal_tx_count:
        recommendation["max_ltv"] -= 0.05
        recommendation["rationale"].append("High contract interaction risk")

    # Clamp LTV safely
    recommendation["max_ltv"] = max(0.15, min(recommendation["max_ltv"], 0.75))

    return recommendation


def explain_score(wallet_age_days, consistency, token_count):
    reasons = []

    # Wallet age
    if wallet_age_days > 365:
        reasons.append("Wallet age > 1 year")
    elif wallet_age_days > 90:
        reasons.append("Wallet age > 3 months")
    else:
        reasons.append("Very new wallet")

    # Consistency
    if token_count > 5:
        if consistency < 1:
            reasons.append("Consistent weekly activity")
        elif consistency < 2:
            reasons.append("Moderately consistent activity")
        else:
            reasons.append("Highly irregular activity")
    else:
        reasons.append("Limited activity history")

    # Token diversity
    if token_count > 10:
        reasons.append("High token diversity")
    elif token_count > 3:
        reasons.append("Moderate token diversity")
    else:
        reasons.append("Low token diversity")

    return reasons

def score_wallet_internal(wallet: str):
    transfers = fetch_erc20_transfers(wallet)

    age = wallet_age_days_from_erc20(transfers)
    consistency = activity_consistency(transfers)
    tokens = token_diversity(transfers)

    score = risk_score(age, consistency, tokens)
    tier = risk_tier(score)
    reasons = explain_score(age, consistency, tokens)

    return {
        "wallet": wallet,
        "wallet_age_days": age,
        "consistency_score": round(consistency, 3),
        "unique_tokens": tokens,
        "score": score,
        "risk_tier": tier,
        "reasons": reasons
    }

def score_breakdown(
    wallet_age_days,
    consistency,
    token_count,
    counterparty_count,
    stable_ratio,
    normal_tx_count,
    internal_tx_count
):
    breakdown = {
        "gate_triggered": False,
        "components": {
            "wallet_age": {"points": 0, "note": ""},
            "consistency": {"points": 0, "note": ""},
            "token_diversity": {"points": 0, "note": ""},
            "counterparties": {"points": 0, "note": ""},
            "stablecoin_behavior": {"points": 0, "note": ""},
            "normal_activity": {"points": 0, "note": ""},
            "contract_activity": {"points": 0, "note": ""},
        },
        "reasons": [],
        "warnings": []
    }

    # --------------------
    # Hard gate
    # --------------------
    if wallet_age_days < 30 or token_count == 0:
        breakdown["gate_triggered"] = True
        breakdown["warnings"].append(
            "Insufficient on-chain history (new wallet or no token activity)."
        )
        return breakdown

    # --------------------
    # Wallet age
    # --------------------
    if wallet_age_days > 365:
        breakdown["components"]["wallet_age"]["points"] = 40
        breakdown["components"]["wallet_age"]["note"] = "Wallet older than 1 year."
        breakdown["reasons"].append("Long wallet history.")
    elif wallet_age_days > 90:
        breakdown["components"]["wallet_age"]["points"] = 25
        breakdown["components"]["wallet_age"]["note"] = "Wallet older than 90 days."
        breakdown["reasons"].append("Moderate wallet history.")
    else:
        breakdown["components"]["wallet_age"]["points"] = 10
        breakdown["components"]["wallet_age"]["note"] = "Wallet younger than 90 days."

    # --------------------
    # Consistency
    # --------------------
    if token_count > 5:
        if consistency < 1:
            breakdown["components"]["consistency"]["points"] = 30
            breakdown["components"]["consistency"]["note"] = "Stable weekly activity."
            breakdown["reasons"].append("Consistent activity over time.")
        elif consistency < 2:
            breakdown["components"]["consistency"]["points"] = 15
            breakdown["components"]["consistency"]["note"] = "Some activity variability."
            breakdown["reasons"].append("Moderately consistent activity.")
        else:
            breakdown["components"]["consistency"]["points"] = 5
            breakdown["components"]["consistency"]["note"] = "Highly bursty / irregular activity."
            breakdown["reasons"].append("Irregular activity patterns (higher risk).")
    else:
        breakdown["warnings"].append(
            "Consistency not evaluated due to low activity breadth."
        )

    # --------------------
    # Token diversity
    # --------------------
    if token_count > 10:
        breakdown["components"]["token_diversity"]["points"] = 30
        breakdown["components"]["token_diversity"]["note"] = "Interacted with many distinct tokens."
        breakdown["reasons"].append("High token diversity.")
    elif token_count > 3:
        breakdown["components"]["token_diversity"]["points"] = 15
        breakdown["components"]["token_diversity"]["note"] = "Interacted with a few distinct tokens."
        breakdown["reasons"].append("Moderate token diversity.")
    else:
        breakdown["components"]["token_diversity"]["points"] = 5
        breakdown["components"]["token_diversity"]["note"] = "Very low token diversity."

    # --------------------
    # Counterparties
    # --------------------
    if counterparty_count > 200:
        breakdown["components"]["counterparties"]["points"] = 10
        breakdown["components"]["counterparties"]["note"] = "Very high number of counterparties."
        breakdown["reasons"].append("High counterparty diversity (strong real-usage signal).")
    elif counterparty_count > 50:
        breakdown["components"]["counterparties"]["points"] = 7
        breakdown["components"]["counterparties"]["note"] = "High number of counterparties."
        breakdown["reasons"].append("Good counterparty diversity.")
    elif counterparty_count > 10:
        breakdown["components"]["counterparties"]["points"] = 3
        breakdown["components"]["counterparties"]["note"] = "Some counterparty diversity."
    else:
        breakdown["components"]["counterparties"]["note"] = "Low counterparty diversity."
        breakdown["warnings"].append(
            "Low counterparty diversity may indicate a single-purpose wallet."
        )

    # --------------------
    # Stablecoin behavior
    # --------------------
    if stable_ratio > 0.60:
        breakdown["components"]["stablecoin_behavior"]["points"] = 10
        breakdown["components"]["stablecoin_behavior"]["note"] = (
            f"High stablecoin usage ({stable_ratio:.2f})."
        )
        breakdown["reasons"].append("High stablecoin usage (lower volatility behavior).")
    elif stable_ratio > 0.30:
        breakdown["components"]["stablecoin_behavior"]["points"] = 5
        breakdown["components"]["stablecoin_behavior"]["note"] = (
            f"Moderate stablecoin usage ({stable_ratio:.2f})."
        )
        breakdown["reasons"].append("Moderate stablecoin usage.")
    else:
        breakdown["components"]["stablecoin_behavior"]["note"] = (
            f"Low stablecoin usage ({stable_ratio:.2f})."
        )

    # --------------------
    # Normal tx activity
    # --------------------
    if normal_tx_count > 200:
        breakdown["components"]["normal_activity"]["points"] = 6
        breakdown["components"]["normal_activity"]["note"] = (
            f"High normal tx activity ({normal_tx_count})."
        )
        breakdown["reasons"].append("High normal transaction activity.")
    elif normal_tx_count > 50:
        breakdown["components"]["normal_activity"]["points"] = 3
        breakdown["components"]["normal_activity"]["note"] = (
            f"Moderate normal tx activity ({normal_tx_count})."
        )
        breakdown["reasons"].append("Moderate normal transaction activity.")
    else:
        breakdown["components"]["normal_activity"]["note"] = (
            f"Low normal tx activity ({normal_tx_count})."
        )

    # --------------------
    # Internal tx activity
    # --------------------
    if internal_tx_count > 50:
        breakdown["components"]["contract_activity"]["points"] = 6
        breakdown["components"]["contract_activity"]["note"] = (
            f"High internal tx activity ({internal_tx_count})."
        )
        breakdown["reasons"].append("High contract interaction activity.")
    elif internal_tx_count > 10:
        breakdown["components"]["contract_activity"]["points"] = 3
        breakdown["components"]["contract_activity"]["note"] = (
            f"Moderate internal tx activity ({internal_tx_count})."
        )
        breakdown["reasons"].append("Moderate contract interaction activity.")
    else:
        breakdown["components"]["contract_activity"]["note"] = (
            f"Low internal tx activity ({internal_tx_count})."
        )

    return breakdown

def risk_flags(
    wallet_age_days,
    consistency,
    token_count,
    counterparty_count,
    stable_ratio,
    normal_tx_count,
    internal_tx_count
):
    flags = []

    # Cold start / thin history
    if wallet_age_days < 30 or token_count == 0:
        flags.append({"flag": "low_history", "severity": "high", "note": "New wallet or no token activity."})

    # Behavior irregularity
    if consistency > 2:
        flags.append({"flag": "bursty_activity", "severity": "medium", "note": "Highly irregular activity over time."})

    # Very low breadth
    if token_count <= 3:
        flags.append({"flag": "low_token_diversity", "severity": "medium", "note": "Few distinct tokens interacted with."})

    if counterparty_count <= 10:
        flags.append({"flag": "low_counterparty_diversity", "severity": "medium", "note": "Few distinct counterparties."})

    # Contract-heavy behavior (can be riskier depending on context)
    if internal_tx_count > normal_tx_count and internal_tx_count > 10:
        flags.append({"flag": "contract_heavy_activity", "severity": "medium", "note": "Internal txs exceed normal txs."})

    # Low stablecoin usage (more volatility exposure)
    if stable_ratio < 0.10 and token_count > 3:
        flags.append({"flag": "low_stablecoin_usage", "severity": "low", "note": "Limited stablecoin usage observed."})

    return flags


def compute_wallet_result(wallet: str, profile: str = "conservative"):
    wallet = validate_wallet(wallet)

    cached = cache_get(f"{wallet}:{profile}")
    if cached:
        return {**cached, "cached": True}

    transfers = fetch_erc20_transfers(wallet)
    normal_txs = fetch_normal_txs(wallet)
    internal_txs = fetch_internal_txs(wallet)

    # ✅ counts (fix)
    normal_tx_count = len(normal_txs)
    internal_tx_count = len(internal_txs)

    age = wallet_age_days_from_erc20(transfers)
    consistency = activity_consistency(transfers)
    tokens = token_diversity(transfers)
    counterparties = unique_counterparties(transfers, wallet)
    stable_ratio = stablecoin_ratio(transfers)

    score = risk_score(age, consistency, tokens, counterparties, stable_ratio, normal_tx_count, internal_tx_count)
    tier = risk_tier(score)

    decision = credit_decision(age, tokens, score, tier)

    breakdown = score_breakdown(
        age, consistency, tokens, counterparties,
        stable_ratio, normal_tx_count, internal_tx_count
    )

    recommendation = collateral_recommendation(
        score=score,
        risk_tier=tier,
        consistency=consistency,
        stable_ratio=stable_ratio,
        normal_tx_count=normal_tx_count,
        internal_tx_count=internal_tx_count,
        profile=profile
    )

    # 🔒 HARD GATE — override recommendation if DENY
    if decision["status"] == "DENY":
        recommendation = {
            "profile": profile,
            "max_ltv": 0.0,
            "collateral_factor": None,
            "suggested_interest_rate_apr": None,
            "policy": "deny",
            "rationale": ["Denied due to insufficient history or elevated risk."]
        }

    test_summary = {
        "score": score,
        "risk_tier": tier,
        "normal_tx_count": normal_tx_count,
        "internal_tx_count": internal_tx_count,
    }

    flags = risk_flags(
          age, consistency, tokens, counterparties,
          stable_ratio, normal_tx_count, internal_tx_count
    )
  


    result = {
        "wallet": wallet,
        "wallet_age_days": age,
        "consistency_score": round(consistency, 3),
        "unique_tokens": tokens,
        "unique_counterparties": counterparties,
        "stablecoin_ratio": round(stable_ratio, 3),
        "normal_tx_count": normal_tx_count,
        "internal_tx_count": internal_tx_count,
        "score": score,
        "risk_tier": tier,
        "decision": decision,
        "recommendation": recommendation,
        "risk_flags": flags,
        "explainability": breakdown,
        "test_summary": test_summary
    }

    cache_set(f"{wallet}:{profile}", result)
    return {**result, "cached": False}





# -------------------------
# API Endpoint
# -------------------------
@app.get("/score")
def score_wallet(wallet: str, profile: str = "conservative"):
    return compute_wallet_result(wallet, profile)

    transfers = fetch_erc20_transfers(wallet)
    normal_txs = fetch_normal_txs(wallet)
    internal_txs = fetch_internal_txs(wallet)

    normal_tx_count = len(normal_txs)
    internal_tx_count = len(internal_txs)
  


    age = wallet_age_days_from_erc20(transfers)
    consistency = activity_consistency(transfers)
    tokens = token_diversity(transfers)
    counterparties = unique_counterparties(transfers, wallet)
    stable_ratio = stablecoin_ratio(transfers)


    score = risk_score(age, consistency, tokens, counterparties, stable_ratio, normal_tx_count, internal_tx_count)
    tier = risk_tier(score)
    breakdown = score_breakdown(age, consistency, tokens, counterparties, stable_ratio, normal_tx_count, internal_tx_count)
    recommendation = collateral_recommendation(
    score=score,
    risk_tier=tier,
    consistency=consistency,
    stable_ratio=stable_ratio,
    normal_tx_count=normal_tx_count,
    internal_tx_count=internal_tx_count,
    profile=profile
)

@app.get("/compare")
def compare(walletA: str, walletB: str, profile: str = "conservative"):
    a = compute_wallet_result(walletA, profile)
    b = compute_wallet_result(walletB, profile)

    # Decide winner by score
    if a["score"] > b["score"]:
        winner = "walletA"
    elif b["score"] > a["score"]:
        winner = "walletB"
    else:
        winner = "tie"

    summary = {
        "profile": profile,
        "walletA": walletA,
        "walletB": walletB,
        "winner": winner,
        "walletA_score": a["score"],
        "walletB_score": b["score"],
        "walletA_risk_tier": a["risk_tier"],
        "walletB_risk_tier": b["risk_tier"],
        "reason": (
            "Higher score indicates lower estimated risk based on current signals."
            if winner != "tie"
            else "Scores are equal under current signals."
        )
    }

    return summary

@app.get("/features")
def features(wallet: str, profile: str = "conservative"):
    r = compute_wallet_result(wallet, profile)

    # Return ONLY numeric + categorical features (ML-ready)
    return {
        "wallet": r["wallet"],
        "profile": profile,
        "features": {
            "wallet_age_days": r["wallet_age_days"],
            "consistency_score": r["consistency_score"],
            "unique_tokens": r["unique_tokens"],
            "unique_counterparties": r["unique_counterparties"],
            "stablecoin_ratio": r["stablecoin_ratio"],
            "normal_tx_count": r["normal_tx_count"],
            "internal_tx_count": r["internal_tx_count"],
            "risk_tier": r["risk_tier"],   # label-like categorical
            "score": r["score"],           # label-like numeric
        },
        "risk_flags": r.get("risk_flags", [])
    }




    # -------- Test Summary (for debugging / iteration) --------
    test_summary = {
         "score": score,
         "risk_tier": tier,
         "normal_tx_count": normal_tx_count,
         "internal_tx_count": internal_tx_count,
    }



    result = {
        "wallet": wallet,
        "wallet_age_days": age,
        "consistency_score": round(consistency, 3),
        "unique_tokens": tokens,
        "unique_counterparties": counterparties,
        "stablecoin_ratio": round(stable_ratio, 3),
        "normal_tx_count": normal_tx_count,
        "internal_tx_count": internal_tx_count,
        "score": score,
        "risk_tier": tier,
        "recommendation": recommendation,
        "explainability": breakdown,
        "test_summary": test_summary
    }

    cache_set(wallet, result)
    return {**result, "cached": False}
