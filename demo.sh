#!/bin/bash
set -e

BASE="http://127.0.0.1:8000"

WALLET_A="0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
WALLET_B="0xC072892b578e3a51B2D994C4f3fa9dF5B3199713"

echo "== SCORE (AAVE) =="
curl -s "${BASE}/score?wallet=${WALLET_A}&profile=aave"
echo ""

echo "== SCORE (MORPHO) =="
curl -s "${BASE}/score?wallet=${WALLET_A}&profile=morpho"
echo ""

echo "== COMPARE (AAVE) =="
curl -s "${BASE}/compare?walletA=${WALLET_A}&walletB=${WALLET_B}&profile=aave"
echo ""

echo "== FEATURES (AAVE) =="
curl -s "${BASE}/features?wallet=${WALLET_B}&profile=aave"
echo ""
