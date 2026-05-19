"""Tests for the Cloud Run relay (cloud/main.py)."""
import json

import pytest


@pytest.fixture(autouse=True)
def set_webhook_secret(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "testsecret")


@pytest.fixture()
def client(mocker):
    mocker.patch("cloud.main._store_alert")
    import importlib

    import cloud.main as relay

    importlib.reload(relay)
    relay.app.config["TESTING"] = True
    with relay.app.test_client() as c:
        yield c


VALID_PAYLOAD = {
    "symbol": "BTCUSDT",
    "timeframe": "15",
    "price": 65000.0,
    "ema20": 64800.0,
    "ema50": 64200.0,
    "rsi14": 58.3,
    "macd_hist": 45.2,
    "atr14": 320.5,
    "vol_ratio": 1.2,
}

HEADERS = {"X-Webhook-Secret": "testsecret", "Content-Type": "application/json"}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["status"] == "ok"
    assert data["role"] == "relay"


def test_valid_webhook_stored(client, mocker):
    mock_store = mocker.patch("cloud.main._store_alert")
    r = client.post("/webhook", data=json.dumps(VALID_PAYLOAD), headers=HEADERS)
    assert r.status_code == 200
    data = json.loads(r.data)
    assert data["status"] == "ok"
    assert data["symbol"] == "BTCUSDT"
    mock_store.assert_called_once()
    stored = mock_store.call_args[0][0]
    assert stored["symbol"] == "BTCUSDT"


def test_missing_secret_header_rejected(client):
    r = client.post(
        "/webhook",
        data=json.dumps(VALID_PAYLOAD),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 401


def test_wrong_secret_rejected(client):
    bad_headers = {**HEADERS, "X-Webhook-Secret": "wrongsecret"}
    r = client.post("/webhook", data=json.dumps(VALID_PAYLOAD), headers=bad_headers)
    assert r.status_code == 401


def test_missing_symbol_rejected(client, mocker):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "symbol"}
    r = client.post("/webhook", data=json.dumps(payload), headers=HEADERS)
    assert r.status_code == 400
    assert b"symbol" in r.data


def test_missing_timeframe_rejected(client, mocker):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "timeframe"}
    r = client.post("/webhook", data=json.dumps(payload), headers=HEADERS)
    assert r.status_code == 400


def test_invalid_json_rejected(client):
    r = client.post("/webhook", data="not json", headers=HEADERS)
    assert r.status_code == 400
    assert b"invalid JSON" in r.data


def test_unconfigured_secret_returns_401(monkeypatch, mocker):
    mocker.patch("cloud.main._store_alert")
    import importlib

    import cloud.main as relay

    importlib.reload(relay)
    relay.WEBHOOK_SECRET = ""
    relay.app.config["TESTING"] = True
    with relay.app.test_client() as c:
        r = c.post("/webhook", data=json.dumps(VALID_PAYLOAD), headers=HEADERS)
    assert r.status_code == 401


def test_symbol_uppercased(client, mocker):
    mock_store = mocker.patch("cloud.main._store_alert")
    payload = {**VALID_PAYLOAD, "symbol": "btcusdt"}
    r = client.post("/webhook", data=json.dumps(payload), headers=HEADERS)
    assert r.status_code == 200
    stored = mock_store.call_args[0][0]
    assert stored["symbol"] == "BTCUSDT"
