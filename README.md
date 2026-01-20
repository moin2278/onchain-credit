# On-Chain Credit Risk Scoring API

A production-style FastAPI service that evaluates Ethereum wallet credit risk using on-chain behavior.

## What this does
- Scores wallets using ERC20 activity, transaction patterns, and counterparties
- Produces a **risk tier**, **credit decision**, and **collateral recommendation**
- Designed for DeFi lending protocols (Aave / Morpho-style policies)

## Key Features
- Wallet validation
- ERC20 + normal + internal tx analysis (Etherscan V2)
- Risk flags (new wallet, bursty activity, low diversity, etc.)
- Hard DENY gate for insufficient history
- Explainability breakdown (feature-level points)
- In-memory caching
- REST API (FastAPI)

## Example Endpoints
- `/score?wallet=0x...&profile=aave`
- `/features?wallet=0x...&profile=aave`
- `/compare?walletA=0x...&walletB=0x...`

## Sample Output
```json
{
  "risk_tier": "LOW",
  "decision": "ALLOW",
  "max_ltv": 0.65,
  "score": 100
}
