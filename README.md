# On-Chain Credit Risk Scoring API

An explainable wallet risk and credit decision engine for DeFi lending, built on Ethereum on-chain behavior.

**📄 Read the research: [Predicting Aave V3 Liquidations at Borrow Time](RESEARCH_NOTE.md)** — a three-round backtest (including the failures) showing hand-tuned "wallet reputation" scores carry no signal, while a fitted model on borrowing-history features reaches CV AUC 0.72 at borrow time. Fully reproducible with the pipeline in [`backtest/`](backtest/).

Given any Ethereum address, the API produces:

- A **0–100 risk score** with a feature-level point breakdown (full explainability)
- A **risk tier** — `LOW` / `MEDIUM` / `HIGH` / `UNKNOWN`
- **Named risk flags** — `new_wallet`, `bursty_activity`, `low_counterparty_diversity`, `history_truncated`, and more
- A **credit decision** — `ALLOW` / `LIMIT` / `DENY`, with hard DENY gates for insufficient history
- A **protocol-style recommendation** — max LTV and indicative APR via profile presets (`aave`, `morpho`, `conservative`)
- A **temporal trajectory** — is this wallet's behavior improving or deteriorating, and *why* (named drivers)

## Why this exists

DeFi lending is still constrained by over-collateralization and coarse risk heuristics. Most analytics tools answer "what happened." This system aims at "what does it mean" — turning raw wallet behavior into explainable, actionable lending policy.

## Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Liveness + config check |
| `GET /score?wallet=0x...&profile=aave` | Score, tier, flags, decision, LTV/APR recommendation |
| `GET /features?wallet=0x...` | ML-ready feature export |
| `GET /compare?walletA=0x...&walletB=0x...` | Side-by-side scoring of two wallets |
| `GET /trajectory?wallet=0x...` | Current vs. previous window, with trend drivers |

Interactive docs at `/docs` (Swagger) once running.

## Quickstart

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure (never commit your key — see .env.example)
export ETHERSCAN_API_KEY=your_key_here

# 3. Run
uvicorn api.main:app --reload

# 4. Try it
./demo.sh
```

## Architecture

```
api/
  main.py        # FastAPI endpoints (thin layer, validation, caching)
  etherscan.py   # Rate-limit-safe Etherscan V2 client (throttle, backoff, paging)
  features.py    # Feature computation (pure aggregation + fetch orchestration)
  scoring.py     # Explainable scoring, risk flags, tiers, credit decisions, profiles
  trajectory.py  # Temporal deltas, trend classification, named drivers
tests/           # Unit + API tests (no network required)
```

Data source: Etherscan V2 (normal, internal, and ERC-20 transactions), fetched with free-tier-safe throttling, exponential backoff, and pagination within Etherscan's `page × offset ≤ 10,000` constraint. Truncated histories are surfaced as an explicit risk flag rather than silently dropped.

## Reproduce the research

Anyone can rerun the full study with a free Etherscan API key:

```bash
export ETHERSCAN_API_KEY=your_free_key   # etherscan.io/myapikey
pip install -r requirements.txt -r requirements-backtest.txt scikit-learn

python -m backtest.pull_events --months 18                      # pull Aave V3 events
python -m backtest.build_dataset_borrow_anchored --cases 300 --controls 300
python -m backtest.train_model                                  # CV AUC + held-out tiers
```

See [`backtest/README.md`](backtest/README.md) for design details and caveats.

## Live website + deploy (Render)

`web/index.html` is a full landing site with a live scoring terminal, served at `/`
by the API itself. `/score_model` scores wallets with the trained backtest model
(requires `model.json` in the repo root - copy your trained
`data/backtest/model.json` there). Public endpoints are rate-limited to
20 scores/hour per IP.

Deploy: Render -> New Web Service -> connect this repo ->
Build: `pip install -r requirements.txt` -> Start: from Procfile ->
add env var `ETHERSCAN_API_KEY`.

## Development

```bash
pip install -r requirements-dev.txt
pytest -q
```

CI runs the test suite and a secret-leak guard on every push and PR.

## Honest limitations (current version)

- **Heuristic scoring, not yet calibrated.** Tiers are relative rankings, not calibrated default probabilities. Backtesting against Aave/Morpho liquidation events is the next milestone.
- **Single chain (Ethereum mainnet), single source (Etherscan).** Count-based features; no USD normalization or decoded protocol interactions yet.
- **Wallet-level, not entity-level.** Fresh-wallet Sybil resistance is out of scope for v1; scores are best used as collateral/LTV adjustment inputs, not identity credit.
- **In-memory cache and throttle** are per-process — run single-worker or add Redis before scaling out.

## Roadmap

1. Ground-truth dataset: features of liquidated vs. non-liquidated Aave/Morpho borrowers; backtest and calibrate tiers
2. Decoded protocol interactions (Aave, Morpho, Compound, Uniswap, Lido) and USD-denominated features
3. Multi-chain coverage (EVM L2s)
4. Entity clustering for Sybil-aware scoring
