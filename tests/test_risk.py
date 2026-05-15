import pytest

import app.risk as risk
from app.risk import validate_signal

VALID_PAYLOAD = {
    "symbol": "BTCUSDT",
    "action": "BUY",
    "price": 65000.0,
    "tp_pct": 1.0,
    "sl_pct": 0.5,
    "size_usdt": 20.0,
}


def test_valid_payload_passes():
    validate_signal(VALID_PAYLOAD)


def test_valid_sell_payload_passes():
    validate_signal({**VALID_PAYLOAD, "action": "SELL"})


def test_close_requires_only_symbol_and_action():
    validate_signal({"symbol": "BTCUSDT", "action": "CLOSE"})


def test_close_missing_symbol_raises():
    with pytest.raises(ValueError, match="symbol"):
        validate_signal({"action": "CLOSE"})


def test_missing_symbol():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "symbol"}
    with pytest.raises(ValueError, match="symbol"):
        validate_signal(payload)


def test_missing_action():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "action"}
    with pytest.raises(ValueError, match="action"):
        validate_signal(payload)


def test_missing_price():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "price"}
    with pytest.raises(ValueError, match="price"):
        validate_signal(payload)


def test_missing_tp_pct():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "tp_pct"}
    with pytest.raises(ValueError, match="tp_pct"):
        validate_signal(payload)


def test_missing_sl_pct():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "sl_pct"}
    with pytest.raises(ValueError, match="sl_pct"):
        validate_signal(payload)


def test_missing_size_usdt():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "size_usdt"}
    with pytest.raises(ValueError, match="size_usdt"):
        validate_signal(payload)


def test_invalid_action():
    with pytest.raises(ValueError, match="Invalid action"):
        validate_signal({**VALID_PAYLOAD, "action": "HOLD"})


def test_price_zero():
    with pytest.raises(ValueError, match="price must be > 0"):
        validate_signal({**VALID_PAYLOAD, "price": 0})


def test_price_negative():
    with pytest.raises(ValueError, match="price must be > 0"):
        validate_signal({**VALID_PAYLOAD, "price": -100})


def test_size_usdt_exceeds_max():
    with pytest.raises(ValueError, match="MAX_SIZE_USDT"):
        validate_signal({**VALID_PAYLOAD, "size_usdt": risk.MAX_SIZE_USDT + 1})


def test_size_usdt_zero():
    with pytest.raises(ValueError, match="size_usdt must be > 0"):
        validate_signal({**VALID_PAYLOAD, "size_usdt": 0})


def test_sl_pct_exceeds_max():
    with pytest.raises(ValueError, match="MAX_SL_PCT"):
        validate_signal({**VALID_PAYLOAD, "sl_pct": risk.MAX_SL_PCT + 0.1})


def test_sl_pct_zero():
    with pytest.raises(ValueError, match="sl_pct must be > 0"):
        validate_signal({**VALID_PAYLOAD, "sl_pct": 0})


def test_tp_pct_zero():
    with pytest.raises(ValueError, match="tp_pct must be > 0"):
        validate_signal({**VALID_PAYLOAD, "tp_pct": 0})


def test_tp_sl_ratio_below_minimum():
    # sl=1.0, tp=1.0 → ratio=1.0 < 1.2
    with pytest.raises(ValueError, match="MIN_TP_SL_RATIO"):
        validate_signal({**VALID_PAYLOAD, "tp_pct": 1.0, "sl_pct": 1.0})


def test_tp_sl_ratio_exactly_at_minimum():
    # tp=1.2, sl=1.0 → ratio=1.2 == MIN_TP_SL_RATIO, should pass
    validate_signal({**VALID_PAYLOAD, "tp_pct": 1.2, "sl_pct": 1.0})


def test_allowed_symbols_whitelist(monkeypatch):
    monkeypatch.setattr(risk, "ALLOWED_SYMBOLS", ["BTCUSDT", "ETHUSDT"])
    validate_signal(VALID_PAYLOAD)


def test_symbol_not_in_whitelist(monkeypatch):
    monkeypatch.setattr(risk, "ALLOWED_SYMBOLS", ["ETHUSDT"])
    with pytest.raises(ValueError, match="ALLOWED_SYMBOLS"):
        validate_signal(VALID_PAYLOAD)
