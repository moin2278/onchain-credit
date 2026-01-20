# Onchain Credit Risk Engine

An explainable, on-chain wallet risk scoring and credit decision engine for DeFi protocols.

## What this does
- Scores Ethereum wallets using real on-chain behavior
- Assigns risk tiers (LOW / MEDIUM / HIGH)
- Generates collateral & interest rate recommendations
- Hard-gates new or risky wallets (DENY vs ALLOW)
- Fully explainable (human-readable reasons & flags)

## API Endpoints
- `/score` – Wallet risk score + decision
- `/features` – Raw wallet features & flags
- `/compare` – Compare two wallets side-by-side

## Profiles
Supports protocol-specific risk profiles:
- `aave`
- `morpho`
- `conservative` (default)

## Demo
Run a local demo:

```bash
uvicorn api.main:app --reload
./demo.sh
