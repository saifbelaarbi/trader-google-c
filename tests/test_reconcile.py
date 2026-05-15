import pytest

from app.reconcile import run_reconciliation


@pytest.fixture
def mock_deps(mocker):
    mock_broker = mocker.patch("app.reconcile.broker")
    mock_state = mocker.patch("app.reconcile.state")
    return mock_broker, mock_state


def test_firestore_position_also_open_on_binance_not_cleared(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_all_positions.return_value = [{"symbol": "BTCUSDT", "side": "BUY"}]
    mock_broker.get_open_positions.return_value = [{"symbol": "BTCUSDT", "positionAmt": "0.001"}]

    result = run_reconciliation()

    assert result["checked"] == 1
    assert result["cleared"] == []
    mock_state.clear_position.assert_not_called()


def test_firestore_position_not_on_binance_is_cleared(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_all_positions.return_value = [{"symbol": "BTCUSDT", "side": "BUY"}]
    mock_broker.get_open_positions.return_value = []

    result = run_reconciliation()

    assert result["checked"] == 1
    assert "BTCUSDT" in result["cleared"]
    mock_state.clear_position.assert_called_once_with("BTCUSDT")
    mock_state.log_trade.assert_called_once()
    logged = mock_state.log_trade.call_args[0][0]
    assert logged["event"] == "reconciled_close"
    assert logged["symbol"] == "BTCUSDT"


def test_empty_firestore_returns_zero(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_all_positions.return_value = []
    mock_broker.get_open_positions.return_value = []

    result = run_reconciliation()

    assert result["checked"] == 0
    assert result["cleared"] == []
    mock_state.clear_position.assert_not_called()


def test_multiple_positions_partial_match(mock_deps):
    mock_broker, mock_state = mock_deps
    mock_state.get_all_positions.return_value = [
        {"symbol": "BTCUSDT", "side": "BUY"},
        {"symbol": "ETHUSDT", "side": "SELL"},
        {"symbol": "SOLUSDT", "side": "BUY"},
    ]
    mock_broker.get_open_positions.return_value = [
        {"symbol": "BTCUSDT", "positionAmt": "0.001"},
    ]

    result = run_reconciliation()

    assert result["checked"] == 3
    assert set(result["cleared"]) == {"ETHUSDT", "SOLUSDT"}
    assert mock_state.clear_position.call_count == 2
    assert mock_state.log_trade.call_count == 2
