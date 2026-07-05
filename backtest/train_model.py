"""Step 4: Train and validate a data-driven risk model (replaces hand-tuned weights).

Fits a logistic regression on the backtest dataset, reports cross-validated
AUC (the honest number), calibrates tier cutoffs on predicted probability,
and evaluates the tier table on a held-out split the model never saw.

Writes data/backtest/model.json with everything needed to score new wallets
(feature names, scaler params, coefficients, tier cutoffs).

Usage:
    pip install scikit-learn
    python -m backtest.train_model
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

BEHAVIORAL = [
    ("log_wallet_age", lambda r: np.log1p(r.get("wallet_age_days", 0))),
    ("log_total_tx", lambda r: np.log1p(r.get("total_tx", 0))),
    ("log_erc20_tx", lambda r: np.log1p(r.get("erc20_tx_count", 0))),
    ("log_unique_tokens", lambda r: np.log1p(r.get("unique_tokens", 0))),
    ("log_counterparties", lambda r: np.log1p(r.get("unique_counterparties", 0))),
    ("consistency", lambda r: r.get("consistency_score", 0)),
    ("stablecoin_ratio", lambda r: r.get("stablecoin_ratio", 0)),
    ("dormant_pre_window", lambda r: 1.0 if r.get("total_tx", 0) == 0 else 0.0),
]
PROTOCOL = [
    ("log_prior_borrows", lambda r: np.log1p(r.get("prior_borrow_count", 0))),
    ("borrows_per_month", lambda r: r.get("borrows_per_month", 0)),
    ("log_days_since_borrow", lambda r: np.log1p(max(0, r.get("days_since_last_borrow", -1)))),
    ("never_borrowed_before", lambda r: 1.0 if r.get("days_since_last_borrow", -1) < 0 else 0.0),
    ("recent_borrow_burst", lambda r: r.get("recent_borrow_burst", 0)),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/backtest")
    ap.add_argument("--high-share", type=float, default=0.30,
                    help="Share of wallets to flag HIGH (top-risk band)")
    args = ap.parse_args()

    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        sys.exit("pip install scikit-learn first.")

    ds_path = Path(args.data) / "dataset.jsonl"
    rows = [json.loads(l) for l in open(ds_path)]
    clean = [r for r in rows if r.get("data_ok", True)]
    has_protocol = any("prior_borrow_count" in r for r in clean)
    feature_defs = BEHAVIORAL + (PROTOCOL if has_protocol else [])
    names = [n for n, _ in feature_defs]

    X = np.array([[f(r) for _, f in feature_defs] for r in clean])
    y = np.array([r["label_liquidated"] for r in clean])
    print(f"Rows: {len(clean)} ({int(y.sum())} liquidated) | "
          f"features: {len(names)} | protocol features: {has_protocol}")
    if not has_protocol:
        print("NOTE: no protocol features found - rebuild the dataset with the "
              "v2 build_dataset.py to include them.\n")

    # Honest number: cross-validated AUC
    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)
    cv = StratifiedKFold(5, shuffle=True, random_state=42)
    aucs = cross_val_score(LogisticRegression(max_iter=2000), Xs, y,
                           cv=cv, scoring="roc_auc")
    print(f"Cross-validated AUC: {aucs.mean():.3f} +/- {aucs.std():.3f}  "
          f"(folds: {np.round(aucs, 3).tolist()})")
    print("Rule of thumb: <0.55 no signal | 0.55-0.65 weak | "
          "0.65-0.75 moderate | >0.75 strong\n")

    # Held-out tier table
    Xtr, Xte, ytr, yte = train_test_split(Xs, y, test_size=0.3,
                                          stratify=y, random_state=42)
    model = LogisticRegression(max_iter=2000).fit(Xtr, ytr)
    p_te = model.predict_proba(Xte)[:, 1]
    p_tr = model.predict_proba(Xtr)[:, 1]

    hi_cut = float(np.quantile(p_tr, 1 - args.high_share))
    lo_cut = float(np.quantile(p_tr, args.high_share))

    def tier(p):
        return "HIGH" if p >= hi_cut else ("LOW" if p <= lo_cut else "MEDIUM")

    tiers = {}
    for t in ("LOW", "MEDIUM", "HIGH"):
        mask = np.array([tier(p) == t for p in p_te])
        n = int(mask.sum())
        if n == 0:
            continue
        rate = float(yte[mask].mean())
        tiers[t] = {"n": n, "liquidation_rate": round(rate, 3)}

    base = float(yte.mean())
    print(f"HELD-OUT tier table (30% of data, never seen in training):")
    print(f"{'Tier':<8}{'n':>5}{'liq rate':>10}{'lift':>7}")
    for t, d in tiers.items():
        lift = d["liquidation_rate"] / base if base else 0
        print(f"{t:<8}{d['n']:>5}{100*d['liquidation_rate']:>9.1f}%{lift:>7.2f}")
    print(f"Base rate: {100*base:.1f}%")
    if "HIGH" in tiers and "LOW" in tiers and tiers["LOW"]["liquidation_rate"] > 0:
        print(f"HIGH/LOW separation: "
              f"{tiers['HIGH']['liquidation_rate']/tiers['LOW']['liquidation_rate']:.2f}x\n")

    # Coefficients (interpretation)
    print(f"{'feature':<24}{'coef':>8}  (positive = raises liquidation odds)")
    for n, c in sorted(zip(names, model.coef_[0]), key=lambda t: -abs(t[1])):
        print(f"{n:<24}{c:>8.3f}")

    # Portable model artifact
    out = {
        "feature_names": names,
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "coefficients": model.coef_[0].tolist(),
        "intercept": float(model.intercept_[0]),
        "tier_cutoffs": {"low_max_p": lo_cut, "high_min_p": hi_cut},
        "cv_auc_mean": float(aucs.mean()),
        "cv_auc_std": float(aucs.std()),
        "n_rows": len(clean),
        "includes_protocol_features": has_protocol,
    }
    out_path = Path(args.data) / "model.json"
    json.dump(out, open(out_path, "w"), indent=2)
    print(f"\nModel -> {out_path}")


if __name__ == "__main__":
    main()
