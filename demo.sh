#!/bin/bash
set -e

BASE="${BASE:-http://127.0.0.1:8000}"

WALLET_A="0x742d35Cc6634C0532925a3b844Bc454e4438f44e"   # active / low risk
WALLET_B="0xC072892b578e3a51B2D994C4f3fa9dF5B3199713"   # medium risk
WALLET_C="0xdCe05440Cd346977875da4aCb90eDf85281fFce7"   # new wallet (expected DENY)

echo "== HEALTH =="
curl -s "${BASE}/health"; echo; echo

echo "== SCORE (AAVE) =="
curl -s "${BASE}/score?wallet=${WALLET_A}&profile=aave"; echo; echo

echo "== SCORE (MORPHO) =="
curl -s "${BASE}/score?wallet=${WALLET_A}&profile=morpho"; echo; echo

echo "== SCORE NEW WALLET (EXPECTED DENY) =="
curl -s "${BASE}/score?wallet=${WALLET_C}&profile=aave"; echo; echo

echo "== COMPARE =="
curl -s "${BASE}/compare?walletA=${WALLET_A}&walletB=${WALLET_B}&profile=aave"; echo; echo

echo "== FEATURES =="
curl -s "${BASE}/features?wallet=${WALLET_B}"; echo; echo

echo "== TRAJECTORY =="
curl -s "${BASE}/trajectory?wallet=${WALLET_A}"; echo
