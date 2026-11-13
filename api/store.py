"""Persistent score cache backed by Postgres (Supabase).

Write-through cache for /score_model: a wallet is computed live at most once
per freshness window, then served instantly from the DB. Also the table the
warm-precompute batch (backtest/precompute_scores.py) writes into.

Degrades gracefully. If DATABASE_URL is unset, psycopg2 is missing, or the DB
is unreachable, every function is a safe no-op (returns None / empty / does
nothing) and the API falls back to live scoring. The DB is an optimization,
never a hard dependency.
"""

import json
import os
from typing import Any, Dict, Optional, Set

try:
    import psycopg2
    import psycopg2.extras
except Exception:  # import guarded so the API still boots without the driver
    psycopg2 = None

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
# How long a cached score stays "fresh" before it's recomputed on next view.
SCORE_TTL_DAYS = int(os.getenv("SCORE_TTL_DAYS", "14"))
_CONNECT_TIMEOUT = 5


def enabled() -> bool:
    return bool(DATABASE_URL and psycopg2 is not None)


def _connect():
    # psycopg2 understands the full libpq URL (the Supabase pooled URI).
    return psycopg2.connect(DATABASE_URL, connect_timeout=_CONNECT_TIMEOUT)


def init_schema() -> None:
    """Create the table + index if absent. Idempotent; safe to call on boot."""
    if not enabled():
        return
    conn = None
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists wallet_scores (
                  wallet            text primary key,
                  risk_probability  double precision not null,
                  risk_tier         text not null,
                  score_json        jsonb not null,
                  source            text not null default 'live',
                  computed_at       timestamptz not null default now()
                );
                create index if not exists wallet_scores_computed_at_idx
                  on wallet_scores (computed_at);
                """
            )
        conn.commit()
    except Exception as e:
        print(f"[store] init_schema skipped: {e}")
    finally:
        if conn is not None:
            conn.close()


def get_cached_score(wallet: str, max_age_days: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Return the stored score dict if present and fresher than the TTL."""
    if not enabled():
        return None
    ttl = SCORE_TTL_DAYS if max_age_days is None else max_age_days
    conn = None
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                select score_json
                  from wallet_scores
                 where wallet = %s
                   and computed_at > now() - (%s || ' days')::interval
                """,
                (wallet.lower(), str(ttl)),
            )
            row = cur.fetchone()
        if row:
            val = row[0]
            return val if isinstance(val, dict) else json.loads(val)
    except Exception as e:
        print(f"[store] get_cached_score miss (error): {e}")
    finally:
        if conn is not None:
            conn.close()
    return None


def get_fresh_wallets(max_age_days: Optional[int] = None) -> Set[str]:
    """Set of wallet addresses already scored within the freshness window."""
    if not enabled():
        return set()
    ttl = SCORE_TTL_DAYS if max_age_days is None else max_age_days
    conn = None
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                select wallet from wallet_scores
                 where computed_at > now() - (%s || ' days')::interval
                """,
                (str(ttl),),
            )
            return {r[0] for r in cur.fetchall()}
    except Exception as e:
        print(f"[store] get_fresh_wallets error: {e}")
        return set()
    finally:
        if conn is not None:
            conn.close()


def upsert_score(wallet: str, result: Dict[str, Any], source: str = "live") -> None:
    """Insert or refresh a wallet's score."""
    if not enabled():
        return
    conn = None
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into wallet_scores
                    (wallet, risk_probability, risk_tier, score_json, source, computed_at)
                values (%s, %s, %s, %s, %s, now())
                on conflict (wallet) do update set
                    risk_probability = excluded.risk_probability,
                    risk_tier        = excluded.risk_tier,
                    score_json       = excluded.score_json,
                    source           = excluded.source,
                    computed_at      = now()
                """,
                (
                    wallet.lower(),
                    float(result.get("risk_probability", 0.0)),
                    str(result.get("risk_tier", "")),
                    psycopg2.extras.Json(result),
                    source,
                ),
            )
        conn.commit()
    except Exception as e:
        print(f"[store] upsert_score skipped: {e}")
    finally:
        if conn is not None:
            conn.close()
