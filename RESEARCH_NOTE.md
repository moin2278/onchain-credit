# Predicting Aave V3 Liquidations at Borrow Time
### A three-round backtest of behavioral wallet risk scoring — including the failures

**Author:** Moin Hasan · github.com/moin2278/onchain-credit · July 2026

---

## TL;DR

We tested whether a wallet's on-chain behavior, observable at the moment it
borrows on Aave V3, predicts liquidation within the next 90 days.

- A hand-tuned "wallet reputation" score — the kind most wallet-scoring
  products ship — had **zero predictive power** (flat tier table).
- A fitted model on the same features plus Aave borrowing-history features
  reaches **cross-validated AUC 0.72** in a leakage-controlled,
  borrow-anchored design (n=525 borrowers, 18 months of Aave V3 mainnet).
- On a held-out set, wallets flagged HIGH at borrow time were liquidated at
  **62.9% vs 33.3%** for LOW (≈1.9x), against a ~51% case-control base rate.
- The strongest signals are **borrower experience and borrowing cadence**,
  not "wallet reputation." Several standard intuitions inverted.

## Why we ran this

Most wallet-scoring approaches assume older, more active, more diversified
wallets are safer borrowers. Nobody seems to publish backtests. We did the
test before building the product.

## Design (round 3 — the one that counts)

- **Unit:** a borrow event on Aave V3 (Ethereum mainnet, 18-month lookback).
- **Label:** wallet liquidated within 90 days of that borrow (case-control:
  ~300 liquidated / ~300 never-liquidated borrowers).
- **Features:** computed strictly from data available at the borrow moment —
  30-day behavioral window ending at the borrow (activity, diversity,
  stablecoin share, consistency) plus Aave borrowing history (prior borrow
  count, cadence, recency). Wallet age computed as of the borrow.
- **No lookahead:** the label lives entirely in the future relative to
  every feature. Controls' outcome windows are fully observed (censored
  borrows excluded).
- **Evaluation:** 5-fold cross-validated AUC; tier table reported only on a
  30% held-out split.

## Results

| Round | Design | Result |
|---|---|---|
| 1 | Hand-tuned heuristic score | **No signal.** HIGH tier liquidated 48.6% vs LOW 54.4% — flat/inverted |
| 2 | Fitted model, liquidation-anchored | AUC 0.74 — but partly an anchoring artifact we identified and rejected |
| 3 | Fitted model, borrow-anchored (production framing) | **AUC 0.720 ± 0.057 (CV)**; held-out HIGH 62.9% vs LOW 33.3% |

## What actually predicts liquidation

Directionally robust findings (logistic coefficients, round 3):

1. **Borrower inexperience.** First-time and low-history borrowers are
   substantially more likely to be liquidated within 90 days. (Part of this
   coefficient's magnitude may reflect residual anchor-selection asymmetry —
   see limitations — but the direction is consistent across rounds.)
2. **Time since last borrow (+).** Returning after long dormancy is a risk
   marker — "rusty borrower" effect.
3. **Counterparty diversity (−).** Wallets transacting with more distinct
   counterparties get liquidated less.
4. **Standard intuitions that FAILED:** wallet age is roughly neutral once
   anchoring is controlled; stablecoin-heavy activity is mildly a *risk*
   marker (consistent with leverage looping), not a safety marker; raw
   activity volume is not protective.

## Limitations (read these before quoting us)

- Case-control base rate (~51%) is not the real-world liquidation rate;
  lifts are relative comparisons within the sample.
- Held-out split is small (~158 wallets); tier rates carry wide error bars.
- Case anchors (earliest trigger borrow) vs control anchors (random mature
  borrow) retain a mild asymmetry that likely inflates the
  borrower-inexperience coefficient. Symmetric anchoring is queued next.
- Single protocol (Aave V3), single chain (Ethereum), count-based
  behavioral features without USD normalization or position data (health
  factor, collateral mix). Position-aware features are the obvious next
  lift and we expect them to raise AUC materially.
- Liquidation is heavily market-driven; behavioral signal is a prior, not
  a crystal ball. AUC 0.72 means useful ranking, not certainty.

## What's next

Larger sample (1,000+1,000), symmetric anchoring, borrow-size and
collateral-mix features decoded from event data, and Morpho Blue as the
second protocol. If you run a lending protocol, curate vaults, or manage
treasury exposure to DeFi credit and want to sanity-check these results or
run them on your own book: the full pipeline is open —
**github.com/moin2278/onchain-credit** — and I'm easy to find.
