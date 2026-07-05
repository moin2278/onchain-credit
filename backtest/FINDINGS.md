# Backtest Findings - Round 1 (Aave V3, 600 wallets, 18 months)

## Headline
The v1 hand-tuned score has NO predictive power for Aave liquidations
(HIGH tier 48.6% liquidation rate vs LOW tier 54.4% - flat/inverted).

## What the data showed
1. Liquidated borrowers are OLDER and MORE active than controls
   (median wallet age 522d vs 105d). Everything v1 rewarded as
   "creditworthy" (age, activity, diversity, stablecoin usage) is
   equal-or-HIGHER among liquidated wallets. Sophisticated, active
   DeFi users run leverage; leverage gets liquidated. Wallet
   reputation != lending risk.
2. A logistic model reaches CV AUC ~0.70, BUT ~all of it comes from
   wallet age, and the age signal is inflated by a design confound:
   round-1 controls were anchored at their FIRST borrow (young by
   construction) while cases anchor at first liquidation (later in
   life). Behavioral features alone: AUC 0.54 = coin flip.
3. ~50% of wallets had ZERO activity in the 30-day pre-window -
   activity-shape features are too sparse at this horizon.

## Round-2 changes (this version)
- build_dataset.py: controls now anchored at a RANDOM borrow event
  (removes the age artifact).
- protocol_features.py: position-aware features (prior borrow count,
  cadence, recency, 90d burst) derived from already-pulled Aave events,
  strictly pre-as-of (leakage-guard unit tested).
- train_model.py: fitted + cross-validated model replaces hand-tuned
  weights; tiers calibrated on predicted probability; tier table
  reported on a held-out split only.

## Interpretation guardrails
- Only trust the CV AUC and the HELD-OUT tier table.
- Round-1 model.json results (4.15x separation) are NOT valid for
  external claims - they ride on the confounded age signal. Rebuild
  the dataset first, then retrain; report those numbers.
