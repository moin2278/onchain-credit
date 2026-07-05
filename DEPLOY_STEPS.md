# Deploy Steps — Do These In Order

The code is fixed, but two things only YOU can do: rotate the leaked key, and push.

## Step 1 — Rotate the Etherscan API key (do this FIRST, takes 2 minutes)

The old key was committed to a public repo, so treat it as compromised even after we scrub history (scrapers archive public repos within minutes of a push).

1. Go to https://etherscan.io/myapikey
2. Delete the old key (the one starting with `HBVI...`)
3. Create a new key
4. On Render: Dashboard → your service → Environment → set `ETHERSCAN_API_KEY` to the new key
5. Locally: `export ETHERSCAN_API_KEY=new_key_here`

## Step 2 — Replace the repo contents and wipe the leaked history

The key exists in old commits, so we replace the entire git history with one clean commit.
Since this is a portfolio project with no collaborators, the simplest safe approach:

```bash
cd onchain-credit-fixed          # this folder
git init
git add .
git commit -m "v1.1: modular architecture, /score + /compare endpoints, tests, CI, secret scrub"
git branch -M main
git remote add origin https://github.com/moin2278/onchain-credit.git
git push --force origin main
```

`--force` replaces the remote history entirely — the leaked key disappears from the repo.

## Step 3 — Purge GitHub's cached views (optional but thorough)

Force-pushing removes commits from the branch, but GitHub can cache orphaned commits.
To fully purge, contact GitHub support or simply: delete the repo on GitHub →
recreate it with the same name → push. Since you rotated the key in Step 1,
this is belt-and-suspenders, not critical.

## Step 4 — Verify

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest -q                          # 22 tests should pass
uvicorn api.main:app --reload      # then in another terminal:
./demo.sh                          # now works — /score and /compare exist
```

Check GitHub → Actions tab: CI (tests + secret-leak guard) should run green on the push.

## Step 5 — Redeploy on Render

Render auto-deploys on push if connected to the repo. Confirm `/health` on your
live URL returns `"etherscan_key_configured": true`.

## What changed (summary)

- **SECURITY**: hardcoded Etherscan key removed from notebook; `.env.example` added; CI secret-leak guard added
- **RESTORED**: `/score` and `/compare` endpoints (documented but missing from the code) — explainable 0–100 score, ALLOW/LIMIT/DENY decisions, LTV/APR per profile (aave/morpho/conservative), hard DENY gates
- **NEW**: `/health` endpoint, wallet address validation (422 on bad input), 503 when key unconfigured
- **REFACTOR**: monolithic `main.py` split into `etherscan.py` / `features.py` / `scoring.py` / `trajectory.py`; the two divergent `trajectory.py` files merged into one (keeps the "drivers" explainability from the src/ version)
- **TESTS**: 22 unit + API tests, zero network required; GitHub Actions CI on every push/PR
- **DOCS**: README rewritten (the pasted chat-instruction residue is gone); honest limitations + roadmap section added
- **MISC**: `demo.sh` updated to match real endpoints; screenshot filenames fixed (colons removed); empty/dead `src/` removed
