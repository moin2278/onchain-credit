# Ground-Truth Backtest

Tests the company's core claim: **wallets scored HIGH risk get liquidated
at a materially higher rate than wallets scored LOW.**

Design: for every Aave V3 borrower liquidated in the lookback period, features
are computed over a 30-day window that ends 30 days BEFORE the liquidation
(no lookahead). Controls are borrowers from the same period who were never
liquidated. Wallet age is corrected to the as-of date to avoid leakage.

## Run it (3 steps)

```bash
export ETHERSCAN_API_KEY=your_key
pip install -r requirements-backtest.txt

# 1. Pull liquidation + borrow events (~10-20 min, resumable)
python -m backtest.pull_events --months 18

# 2. Build point-in-time features (~20-40 min for 300+300 wallets, resumable)
python -m backtest.build_dataset --cases 300 --controls 300

# 3. Analyze + chart (seconds)
python -m backtest.run_backtest
```

Outputs in `data/backtest/`: `results.csv`, `summary.json`, `backtest_chart.png`.

## Reading the results

- **lift_vs_base** per tier: HIGH should be well above 1.0, LOW well below
- **high_vs_low_ratio**: the headline number ("HIGH-tier wallets were
  liquidated Nx more often than LOW-tier")
- **capture_rate vs share_of_wallets_flagged**: flagging everyone is cheating;
  you want high capture while flagging a minority

If the separation is weak, that is equally valuable: it tells us which
features to fix before building more product.

## Round 3 (current recommended run)

Borrow-anchored design - both groups anchored at a borrow event; label is
"liquidated within 90 days of this borrow". This is the production framing
and removes all known anchor confounds. Run:

```bash
mv data/backtest/dataset.jsonl data/backtest/dataset_round2.jsonl  # keep round 2
python -m backtest.build_dataset_borrow_anchored --cases 300 --controls 300
python -m backtest.run_backtest
python -m backtest.train_model
```

## Honest caveats

- Liquidation on Aave is driven heavily by market moves + health factor;
  behavioral features are a prior, not a crystal ball. Expect moderate,
  not magical, separation.
- Controls are borrowers, not random wallets - this is deliberately the
  HARD comparison (both groups use Aave).
- Free-tier Etherscan paging caps very busy wallets (flagged as
  history_truncated).
- Single protocol, single chain (Aave V3 Ethereum). Morpho Blue is
  scaffolded in backtest/__init__.py but unverified.
