from api.scoring import (
    MIN_WALLET_AGE_DAYS,
    compute_risk_flags,
    credit_decision,
    score_wallet,
)


def base_feats(**overrides):
    feats = {
        "wallet": "0x" + "a" * 40,
        "window_days": 30,
        "wallet_age_days": 800,
        "active_days": 20,
        "max_daily_tx": 5,
        "total_tx": 120,
        "consistency_score": 0.66,
        "unique_tokens": 12,
        "unique_counterparties": 25,
        "stablecoin_ratio": 0.4,
        "normal_tx_count": 40,
        "internal_tx_count": 10,
        "erc20_tx_count": 70,
        "history_truncated": False,
        "data_ok": True,
        "errors": {},
    }
    feats.update(overrides)
    return feats


def test_healthy_wallet_is_low_risk_allow():
    scored = score_wallet(base_feats())
    assert scored["risk_tier"] == "LOW"
    assert scored["score"] >= 70
    decision = credit_decision(scored, profile="aave")
    assert decision["decision"] == "ALLOW"
    assert decision["recommendation"]["max_ltv"] == 0.70


def test_new_wallet_hard_deny():
    scored = score_wallet(base_feats(wallet_age_days=5))
    assert scored["hard_deny_reasons"]
    assert scored["risk_tier"] == "HIGH"
    decision = credit_decision(scored)
    assert decision["decision"] == "DENY"
    assert decision["recommendation"]["max_ltv"] == 0.0


def test_empty_wallet_hard_deny():
    scored = score_wallet(base_feats(
        total_tx=0, erc20_tx_count=0, normal_tx_count=0, internal_tx_count=0,
        unique_tokens=0, unique_counterparties=0, active_days=0,
        consistency_score=0.0, stablecoin_ratio=0.0,
    ))
    assert "no activity in scoring window" in scored["hard_deny_reasons"]
    assert credit_decision(scored)["decision"] == "DENY"


def test_data_error_gives_unknown_tier():
    scored = score_wallet(base_feats(data_ok=False))
    assert scored["risk_tier"] == "UNKNOWN"
    assert credit_decision(scored)["decision"] == "DENY"


def test_score_bounded_0_100():
    lo = score_wallet(base_feats(
        wallet_age_days=MIN_WALLET_AGE_DAYS, total_tx=25, max_daily_tx=20,
        erc20_tx_count=0, normal_tx_count=25, internal_tx_count=0,
        unique_tokens=0, unique_counterparties=0,
        consistency_score=0.03, stablecoin_ratio=0.0, active_days=1,
    ))
    hi = score_wallet(base_feats(
        wallet_age_days=3000, total_tx=1000, unique_tokens=100,
        unique_counterparties=200, consistency_score=1.0, stablecoin_ratio=0.5,
    ))
    assert 0 <= lo["score"] <= 100
    assert 0 <= hi["score"] <= 100


def test_explainability_breakdown_present():
    scored = score_wallet(base_feats())
    assert set(scored["breakdown"]) == {
        "wallet_age", "consistency", "token_diversity",
        "counterparty_diversity", "stablecoin_usage", "activity_volume",
    }


def test_bursty_activity_flag():
    feats = base_feats(total_tx=100, max_daily_tx=80)
    flags = {f["flag"] for f in compute_risk_flags(feats)}
    assert "bursty_activity" in flags


def test_unknown_profile_falls_back_to_default():
    scored = score_wallet(base_feats())
    decision = credit_decision(scored, profile="not_a_profile")
    assert decision["profile"] == "aave"
