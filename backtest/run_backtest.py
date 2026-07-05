"""Step 3: Run the backtest analysis.

Scores every wallet in the dataset with api/scoring.py and answers:
"Do HIGH-tier wallets get liquidated more often than LOW-tier wallets?"

Outputs:
    data/backtest/results.csv       per-wallet: tier, score, label
    data/backtest/summary.json      tier table, capture rate, lift
    data/backtest/backtest_chart.png  the headline chart

Usage:
    python -m backtest.run_backtest
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from api.scoring import score_wallet

TIER_ORDER = ["LOW", "MEDIUM", "HIGH", "UNKNOWN"]


def analyze(rows: List[Dict]) -> Dict:
    per_tier = defaultdict(lambda: {"n": 0, "liquidated": 0, "scores": []})
    scored_rows = []

    for feats in rows:
        label = int(feats.get("label_liquidated", 0))
        s = score_wallet(feats)
        tier = s["risk_tier"]
        per_tier[tier]["n"] += 1
        per_tier[tier]["liquidated"] += label
        per_tier[tier]["scores"].append(s["score"])
        scored_rows.append({
            "wallet": feats.get("wallet"),
            "score": s["score"],
            "risk_tier": tier,
            "label_liquidated": label,
        })

    total_n = sum(t["n"] for t in per_tier.values())
    total_liq = sum(t["liquidated"] for t in per_tier.values())
    base_rate = total_liq / total_n if total_n else 0.0

    tiers = {}
    for tier in TIER_ORDER:
        t = per_tier.get(tier)
        if not t or t["n"] == 0:
            continue
        rate = t["liquidated"] / t["n"]
        tiers[tier] = {
            "n": t["n"],
            "liquidated": t["liquidated"],
            "liquidation_rate": round(rate, 4),
            "lift_vs_base": round(rate / base_rate, 2) if base_rate else None,
            "avg_score": round(sum(t["scores"]) / t["n"], 1),
        }

    # Capture rate: share of ALL liquidations that landed in HIGH (+UNKNOWN)
    flagged = sum(per_tier[t]["liquidated"] for t in ("HIGH", "UNKNOWN") if t in per_tier)
    flagged_n = sum(per_tier[t]["n"] for t in ("HIGH", "UNKNOWN") if t in per_tier)

    hi = tiers.get("HIGH", {}).get("liquidation_rate")
    lo = tiers.get("LOW", {}).get("liquidation_rate")

    return {
        "total_wallets": total_n,
        "total_liquidated": total_liq,
        "base_liquidation_rate": round(base_rate, 4),
        "tiers": tiers,
        "capture": {
            "liquidations_captured_in_high_or_unknown": flagged,
            "capture_rate": round(flagged / total_liq, 4) if total_liq else None,
            "share_of_wallets_flagged": round(flagged_n / total_n, 4) if total_n else None,
        },
        "high_vs_low_ratio": round(hi / lo, 2) if hi and lo else None,
        "_scored_rows": scored_rows,
    }


def make_chart(summary: Dict, out_png: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed - skipping chart (pip install matplotlib)")
        return

    tiers = [t for t in TIER_ORDER if t in summary["tiers"]]
    rates = [100 * summary["tiers"][t]["liquidation_rate"] for t in tiers]
    ns = [summary["tiers"][t]["n"] for t in tiers]
    colors = {"LOW": "#2e7d32", "MEDIUM": "#f9a825", "HIGH": "#c62828", "UNKNOWN": "#757575"}

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(tiers, rates, color=[colors[t] for t in tiers])
    ax.axhline(100 * summary["base_liquidation_rate"], ls="--", c="black", lw=1,
               label=f"Base rate {100*summary['base_liquidation_rate']:.1f}%")
    for bar, rate, n in zip(bars, rates, ns):
        ax.text(bar.get_x() + bar.get_width() / 2, rate + 0.5,
                f"{rate:.1f}%\n(n={n})", ha="center", fontsize=10)
    ax.set_ylabel("Realized liquidation rate (%)")
    ax.set_title("Liquidation rate by pre-event risk tier\n"
                 "(features computed 30 days before event - no lookahead)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    print(f"Chart -> {out_png}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/backtest")
    args = ap.parse_args()

    data_dir = Path(args.data)
    ds_path = data_dir / "dataset.jsonl"
    if not ds_path.exists():
        sys.exit("Run `python -m backtest.build_dataset` first.")

    rows = [json.loads(l) for l in open(ds_path)]
    print(f"Loaded {len(rows)} wallets from {ds_path}\n")

    summary = analyze(rows)
    scored = summary.pop("_scored_rows")

    # Write per-wallet results
    csv_path = data_dir / "results.csv"
    with open(csv_path, "w") as f:
        f.write("wallet,score,risk_tier,label_liquidated\n")
        for r in scored:
            f.write(f"{r['wallet']},{r['score']},{r['risk_tier']},{r['label_liquidated']}\n")

    with open(data_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    # Console report
    print(f"{'Tier':<9}{'n':>6}{'liq':>6}{'rate':>8}{'lift':>7}{'avg score':>11}")
    for tier, t in summary["tiers"].items():
        print(f"{tier:<9}{t['n']:>6}{t['liquidated']:>6}"
              f"{100*t['liquidation_rate']:>7.1f}%{t['lift_vs_base']:>7}{t['avg_score']:>11}")
    print(f"\nBase liquidation rate: {100*summary['base_liquidation_rate']:.1f}%")
    if summary["high_vs_low_ratio"]:
        print(f"HIGH-tier wallets were liquidated {summary['high_vs_low_ratio']}x "
              f"more often than LOW-tier wallets.")
    cap = summary["capture"]
    if cap["capture_rate"] is not None:
        print(f"Capture: {100*cap['capture_rate']:.0f}% of liquidations flagged "
              f"while flagging {100*cap['share_of_wallets_flagged']:.0f}% of wallets.")

    make_chart(summary, data_dir / "backtest_chart.png")
    print(f"\nResults -> {csv_path}, summary.json")


if __name__ == "__main__":
    main()
