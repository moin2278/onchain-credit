# On-Chain Credit Scoring API (DeFi)

An explainable wallet risk + credit decision engine for DeFi lending.

This API scores an Ethereum wallet using on-chain behavioral signals, produces:
- Risk tier (LOW / MEDIUM / HIGH)
- Explainability (component breakdown + reasons)
- Risk flags (bursty activity, low history, low diversity, etc.)
- Credit decision (ALLOW / LIMIT / DENY)
- Protocol-style recommendation (LTV / APR) with profile presets (e.g., aave, morpho, conservative)
- Compare endpoint to benchmark two wallets quickly
- Features endpoint for ML-ready export

## Why this exists
DeFi lending is still constrained by over-collateralization and coarse risk heuristics.
This system explores more robust, explainable signals from wallet behavior and turns them into actionable lending policy.

---

## Quickstart

### 1) Install
```bash
pip install -r requirements.txt
