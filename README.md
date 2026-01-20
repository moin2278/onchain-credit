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