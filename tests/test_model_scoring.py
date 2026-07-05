import math

from api.model_scoring import build_feature_vector, score_with_model


def synthetic_model():
    names = ["log_wallet_age", "log_unique_tokens", "never_borrowed_before",
             "recent_borrow_burst"]
    return {
        "feature_names": names,
        "scaler_mean": [4.0, 1.5, 0.5, 1.0],
        "scaler_scale": [1.0, 1.0, 0.5, 1.0],
        "coefficients": [0.5, -0.8, 2.0, 0.3],
        "intercept": 0.0,
        "tier_cutoffs": {"low_max_p": 0.35, "high_min_p": 0.65},
        "cv_auc_mean": 0.72, "n_rows": 600,
    }


def feats(**kw):
    base = {"wallet_age_days": 100, "unique_tokens": 5,
            "days_since_last_borrow": 10, "recent_borrow_burst": 1}
    base.update(kw)
    return base


def test_vector_matches_training_transforms():
    m = synthetic_model()
    v = build_feature_vector(feats(), m["feature_names"])
    assert v[0] == math.log1p(100)
    assert v[2] == 0.0  # has borrowed before


def test_first_time_borrower_raises_risk():
    m = synthetic_model()
    experienced = score_with_model(feats(days_since_last_borrow=10), m)
    novice = score_with_model(feats(days_since_last_borrow=-1), m)
    assert novice["risk_probability"] > experienced["risk_probability"]
    top = novice["drivers"][0]
    assert top["feature"] == "never_borrowed_before"
    assert top["direction"] == "raises risk"


def test_tiers_follow_cutoffs():
    m = synthetic_model()
    hi = score_with_model(feats(days_since_last_borrow=-1, unique_tokens=0), m)
    lo = score_with_model(feats(unique_tokens=60, wallet_age_days=3), m)
    assert hi["risk_tier"] == "HIGH"
    assert lo["risk_tier"] == "LOW"
