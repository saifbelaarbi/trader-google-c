import pytest

from app.trade_engine import handle_signal

VALID_BUY = {
    "symbol": "BTCUSDT",
    "action": "BUY",
    "price": 65000.0,
    "tp_pct": 1.0,
    "sl_pct": 0.5,
    "size_usdt": 20.0,
}

VALID_SELL = {**VALID_BUY, "action": "SELL"}


@pytest.fixture
def mock_deps(mocker):
    mock_broker = mocker.patch("app.trade_engine.broker")
    mock_state = mocker.patch("app.trade_engine.state")
    mock_broker.place_market_order.return_value = {"orderId": 12345}
    mock_broker.set_tp_sl.return_value = ({"orderId": 12346}, {"orderId": 12347})
    return mock_broker, mock_state


def test_buy_no_existing_position(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_position.return_value = None

    result = handle_signal(VALID_BUY)

    assert result["status"] == "opened"
    assert result["symbol"] == "BTCUSDT"
    assert result["side"] == "BUY"
    mock_broker.place_market_order.assert_called_once()
    mock_broker.set_tp_sl.assert_called_once()
    mock_state.save_position.assert_called_once()
    mock_state.log_trade.assert_called_once()


def test_buy_with_existing_position_skipped(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_position.return_value = {"side": "BUY", "entry_price": 64000.0}

    result = handle_signal(VALID_BUY)

    assert result["status"] == "skipped"
    assert "already open" in result["reason"]
    mock_broker.place_market_order.assert_not_called()
    mock_state.save_position.assert_not_called()


def test_sell_tp_sl_inverted(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_position.return_value = None

    result = handle_signal(VALID_SELL)

    assert result["status"] == "opened"
    assert result["side"] == "SELL"
    assert result["tp"] < result["entry"]
    assert result["sl"] > result["entry"]


def test_buy_tp_above_entry_sl_below_entry(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_position.return_value = None

    result = handle_signal(VALID_BUY)

    assert result["tp"] > result["entry"]
    assert result["sl"] < result["entry"]


def test_sell_tp_below_entry_sl_above_entry(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_position.return_value = None

    result = handle_signal(VALID_SELL)

    assert result["tp"] < result["entry"]
    assert result["sl"] > result["entry"]


def test_close_with_existing_position(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_position.return_value = {"side": "BUY", "entry_price": 65000.0}
    mock_broker.close_position.return_value = {"orderId": 99999}

    result = handle_signal({"symbol": "BTCUSDT", "action": "CLOSE"})

    assert result["status"] == "closed"
    assert result["symbol"] == "BTCUSDT"
    mock_broker.close_position.assert_called_once_with("BTCUSDT")
    mock_state.clear_position.assert_called_once_with("BTCUSDT")
    mock_state.log_trade.assert_called_once()


def test_close_no_existing_position_skipped(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_position.return_value = None

    result = handle_signal({"symbol": "BTCUSDT", "action": "CLOSE"})

    assert result["status"] == "skipped"
    assert "no open position" in result["reason"]
    mock_broker.close_position.assert_not_called()


def test_place_market_order_exception_does_not_save_state(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_position.return_value = None
    mock_broker.place_market_order.side_effect = RuntimeError("Binance down")

    with pytest.raises(RuntimeError):
        handle_signal(VALID_BUY)

    mock_state.save_position.assert_not_called()


def test_set_tp_sl_exception_still_has_saved_position(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_position.return_value = None
    mock_broker.set_tp_sl.side_effect = RuntimeError("TP/SL failed")

    with pytest.raises(RuntimeError):
        handle_signal(VALID_BUY)

    # Position was persisted before set_tp_sl so reconciliation can find it
    mock_state.save_position.assert_called_once()


def test_buy_qty_calculation(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_position.return_value = None

    result = handle_signal(VALID_BUY)

    expected_qty = round(20.0 / 65000.0, 6)
    assert result["qty"] == expected_qty


def test_sell_tp_sl_prices(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_position.return_value = None

    result = handle_signal(VALID_SELL)

    price = VALID_SELL["price"]
    expected_tp = round(price * (1 - VALID_SELL["tp_pct"] / 100), 2)
    expected_sl = round(price * (1 + VALID_SELL["sl_pct"] / 100), 2)
    assert result["tp"] == expected_tp
    assert result["sl"] == expected_sl
