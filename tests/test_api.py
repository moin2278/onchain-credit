import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app, _CACHE

client = TestClient(app)

GOOD = "0x742d35cc6634c0532925a3b844bc454e4438f44e"
GOOD2 = "0xc072892b578e3a51b2d994c4f3fa9df5b3199713"


def fake_features(wallet, window_days, offset_days, apikey):
    return {
        "wallet": wallet, "window_days": window_days, "offset_days": offset_days,
        "wallet_age_days": 900, "active_days": 15, "max_daily_tx": 4,
        "total_tx": 100, "consistency_score": 0.5, "unique_tokens": 10,
        "unique_counterparties": 20, "stablecoin_ratio": 0.35,
        "normal_tx_count": 30, "internal_tx_count": 10, "erc20_tx_count": 60,
        "history_truncated": False, "data_ok": True, "errors": {},
    }


def setup_function(_):
    _CACHE.clear()


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_invalid_address_422():
    r = client.get("/score", params={"wallet": "nonsense"})
    assert r.status_code == 422


@patch.dict("os.environ", {"ETHERSCAN_API_KEY": ""})
def test_missing_key_503():
    r = client.get("/score", params={"wallet": GOOD})
    assert r.status_code == 503


@patch.dict("os.environ", {"ETHERSCAN_API_KEY": "test"})
@patch("api.main.compute_features", side_effect=fake_features)
def test_score_shape(_mock):
    r = client.get("/score", params={"wallet": GOOD, "profile": "morpho"})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] in {"ALLOW", "LIMIT", "DENY"}
    assert body["profile"] == "morpho"
    assert "breakdown" in body["explainability"]
    assert 0 <= body["score"] <= 100


@patch.dict("os.environ", {"ETHERSCAN_API_KEY": "test"})
@patch("api.main.compute_features", side_effect=fake_features)
def test_compare_shape(_mock):
    r = client.get("/compare", params={"walletA": GOOD, "walletB": GOOD2})
    assert r.status_code == 200
    body = r.json()
    assert set(body["comparison"]) == {"walletA", "walletB"}


@patch.dict("os.environ", {"ETHERSCAN_API_KEY": "test"})
@patch("api.main.compute_features", side_effect=fake_features)
def test_trajectory_shape(_mock):
    r = client.get("/trajectory", params={"wallet": GOOD})
    assert r.status_code == 200
    body = r.json()
    assert body["trajectory"]["trend"] in {
        "improving", "stable", "slightly_deteriorating", "deteriorating",
    }


@patch.dict("os.environ", {"ETHERSCAN_API_KEY": "test"})
@patch("api.main.compute_features", side_effect=fake_features)
def test_features_cached_on_second_call(_mock):
    r1 = client.get("/features", params={"wallet": GOOD})
    r2 = client.get("/features", params={"wallet": GOOD})
    assert r1.json()["features"]["cached"] is False
    assert r2.json()["features"]["cached"] is True


def test_home_serves_site():
    r = client.get("/")
    assert r.status_code == 200
    assert "Live scoring terminal" in r.text


def test_score_model_503_without_model():
    r = client.get("/score_model", params={"wallet": GOOD})
    assert r.status_code == 503
