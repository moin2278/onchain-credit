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

## Demo
Run a local demo:

```bash
uvicorn api.main:app --reload
./demo.sh
 ## Run Locally

1. Install dependencies:
```bash
pip install -r requirements.txt

## Set your Etherscan API key:

export ETHERSCAN_API_KEY=YOUR_KEY

##Start the API:

uvicorn api.main:app --reload

##The API will be available at:
http://127.0.0.1:8000/docs


This is **documentation**, not a command you’re executing now.

---

### 3️⃣ Save the file
- In nano: `CTRL + O` → Enter → `CTRL + X`
- In VS Code: `Cmd + S`

---

### 4️⃣ Commit and push (THIS PART YOU DO RUN)
```bash
git add README.md
git commit -m "Add run instructions and project description"
git push
