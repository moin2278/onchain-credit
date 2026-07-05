"""Explainable wallet risk scoring and credit decisioning.

Produces:
  - 0-100 score with a feature-level point breakdown (explainability)
  - risk flags (new wallet, bursty activity, low diversity, ...)
  - risk tier (LOW / MEDIUM / HIGH / UNKNOWN)
  - credit decision (ALLOW / LIMIT / DENY) with hard gates
  - protocol-style LTV / APR recommendation via profile presets

NOTE: This scoring model is heuristic and NOT yet calibrated against
realized outcomes (liquidations/defaults). Treat tiers as relative,
not as calibrated probabilities. Backtesting against Aave/Morpho
liquidation events is the roadmap's next milestone.
"""

from typing import Any, Dict, List

# Hard gates
MIN_WALLET_AGE_DAYS = 30

# Tier thresholds on the 0-100 score
TIER_LOW_MIN = 70      # score >= 70  -> LOW risk
TIER_MEDIUM_MIN = 45   # score >= 45  -> MEDIUM risk

# Lending profile presets: max LTV and indicative APR per decision
PROFILES: Dict[str, Dict[str, Dict[str, float]]] = {
    "aave": {
        "ALLOW": {"max_ltv": 0.70, "apr": 5.5},
        "LIMIT": {"max_ltv": 0.50, "apr": 8.0},
        "DENY":  {"max_ltv": 0.00, "apr": 0.0},
    },
    "morpho": {
        "ALLOW": {"max_ltv": 0.75, "apr": 5.0},
        "LIMIT": {"max_ltv": 0.55, "apr": 7.5},
        "DENY":  {"max_ltv": 0.00, "apr": 0.0},
    },
    "conservative": {
        "ALLOW": {"max_ltv": 0.60, "apr": 7.0},
        "LIMIT": {"max_ltv": 0.40, "apr": 10.0},
        "DENY":  {"max_ltv": 0.00, "apr": 0.0},
    },
}
DEFAULT_PROFILE = "aave"


def compute_risk_flags(feats: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Named, human-readable risk flags derived from features."""
    flags: List[Dict[str, Any]] = []
    window_days = feats.get("window_days", 30)

    if feats.get("wallet_age_days", 0) < 90:
        flags.append({
            "flag": "new_wallet",
            "severity": "high",
            "note": f"Wallet is only {feats.get('wallet_age_days', 0)} days old",
        })

    if (feats.get("normal_tx_count", 0) + feats.get("internal_tx_count", 0)) == 0:
        flags.append({
            "flag": "no_eth_activity_in_window",
            "severity": "medium",
            "note": f"No normal/internal tx activity in last {window_days} days",
        })

    if feats.get("erc20_tx_count", 0) == 0:
        flags.append({
            "flag": "no_erc20_activity_in_window",
            "severity": "high",
            "note": f"No ERC-20 activity in last {window_days} days",
        })

    total_tx = feats.get("total_tx", 0)
    max_daily = feats.get("max_daily_tx", 0)
    if total_tx >= 20 and max_daily / max(1, total_tx) > 0.5:
        flags.append({
            "flag": "bursty_activity",
            "severity": "medium",
            "note": "More than half of window activity occurred on a single day",
        })

    if 0 < feats.get("erc20_tx_count", 0) and feats.get("unique_tokens", 0) < 3:
        flags.append({
            "flag": "low_token_diversity",
            "severity": "low",
            "note": f"Only {feats.get('unique_tokens', 0)} unique tokens in window",
        })

    if 0 < feats.get("erc20_tx_count", 0) and feats.get("unique_counterparties", 0) < 3:
        flags.append({
            "flag": "low_counterparty_diversity",
            "severity": "medium",
            "note": f"Only {feats.get('unique_counterparties', 0)} unique counterparties in window",
        })

    if feats.get("history_truncated"):
        flags.append({
            "flag": "history_truncated",
            "severity": "medium",
            "note": "Wallet has more activity than fetched (paging limits). Features may be partial.",
        })

    return flags


def _age_points(age_days: int) -> int:
    if age_days >= 730:
        return 25
    if age_days >= 365:
        return 20
    if age_days >= 180:
        return 15
    if age_days >= 90:
        return 10
    if age_days >= MIN_WALLET_AGE_DAYS:
        return 5
    return 0


def score_wallet(feats: Dict[str, Any]) -> Dict[str, Any]:
    """0-100 explainable score with component breakdown, tier, and hard-gate info."""
    breakdown: Dict[str, int] = {}

    # Components (max 100)
    breakdown["wallet_age"] = _age_points(feats.get("wallet_age_days", 0))                      # 0-25
    breakdown["consistency"] = min(20, round(feats.get("consistency_score", 0.0) * 40))         # 0-20
    breakdown["token_diversity"] = min(15, feats.get("unique_tokens", 0) * 2)                   # 0-15
    breakdown["counterparty_diversity"] = min(15, feats.get("unique_counterparties", 0))        # 0-15
    breakdown["stablecoin_usage"] = min(15, round(feats.get("stablecoin_ratio", 0.0) * 30))     # 0-15
    breakdown["activity_volume"] = min(10, feats.get("total_tx", 0) // 5)                       # 0-10

    # Penalties from flags
    flags = compute_risk_flags(feats)
    flag_names = {f["flag"] for f in flags}
    penalties: Dict[str, int] = {}
    if "no_erc20_activity_in_window" in flag_names:
        penalties["no_erc20_activity_in_window"] = -15
    if "no_eth_activity_in_window" in flag_names:
        penalties["no_eth_activity_in_window"] = -8
    if "bursty_activity" in flag_names:
        penalties["bursty_activity"] = -10
    if "low_counterparty_diversity" in flag_names:
        penalties["low_counterparty_diversity"] = -5
    if "history_truncated" in flag_names:
        penalties["history_truncated"] = -3

    score = sum(breakdown.values()) + sum(penalties.values())
    score = max(0, min(100, score))

    # Hard DENY gates: insufficient history to score at all
    hard_deny_reasons: List[str] = []
    if feats.get("wallet_age_days", 0) < MIN_WALLET_AGE_DAYS:
        hard_deny_reasons.append(f"wallet_age_days < {MIN_WALLET_AGE_DAYS}")
    if feats.get("erc20_tx_count", 0) == 0 and feats.get("total_tx", 0) == 0:
        hard_deny_reasons.append("no activity in scoring window")

    if not feats.get("data_ok", True):
        tier = "UNKNOWN"
    elif hard_deny_reasons:
        tier = "HIGH"
    elif score >= TIER_LOW_MIN:
        tier = "LOW"
    elif score >= TIER_MEDIUM_MIN:
        tier = "MEDIUM"
    else:
        tier = "HIGH"

    return {
        "score": int(score),
        "risk_tier": tier,
        "breakdown": breakdown,
        "penalties": penalties,
        "risk_flags": flags,
        "hard_deny_reasons": hard_deny_reasons,
    }


def credit_decision(scored: Dict[str, Any], profile: str = DEFAULT_PROFILE) -> Dict[str, Any]:
    """Map a scored wallet to ALLOW / LIMIT / DENY plus LTV/APR recommendation."""
    profile = profile.lower()
    preset = PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])

    tier = scored.get("risk_tier", "UNKNOWN")
    if scored.get("hard_deny_reasons") or tier in ("HIGH", "UNKNOWN"):
        decision = "DENY"
    elif tier == "MEDIUM":
        decision = "LIMIT"
    else:
        decision = "ALLOW"

    reasons: List[str] = list(scored.get("hard_deny_reasons", []))
    if not reasons:
        reasons.append(f"risk_tier={tier}, score={scored.get('score')}")

    rec = preset.get(decision, {"max_ltv": 0.0, "apr": 0.0})
    return {
        "decision": decision,
        "profile": profile if profile in PROFILES else DEFAULT_PROFILE,
        "recommendation": {
            "max_ltv": rec["max_ltv"],
            "indicative_apr_pct": rec["apr"],
        },
        "reasons": reasons,
    }
