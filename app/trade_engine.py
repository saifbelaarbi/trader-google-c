import logging
from datetime import datetime

from app import broker, state

logger = logging.getLogger(__name__)


def handle_signal(payload: dict) -> dict:
    symbol = payload["symbol"]
    action = payload["action"]

    if action == "CLOSE":
        position = state.get_position(symbol)
        if position is None:
            return {"status": "skipped", "reason": "no open position for symbol"}

        broker.close_position(symbol)
        state.clear_position(symbol)
        state.log_trade({"event": "close", "symbol": symbol, "action": "CLOSE"})
        logger.info("Closed position for %s", symbol)
        return {"status": "closed", "symbol": symbol}

    position = state.get_position(symbol)
    if position is not None:
        return {"status": "skipped", "reason": "position already open"}

    price = float(payload["price"])
    tp_pct = float(payload["tp_pct"])
    sl_pct = float(payload["sl_pct"])
    size_usdt = float(payload["size_usdt"])
    side = action

    # TODO: use symbol exchange filters (LOT_SIZE stepSize) for correct precision
    qty = round(size_usdt / price, 6)
    if qty == 0:
        raise ValueError(
            f"Calculated qty is 0 for size_usdt={size_usdt} price={price}; increase size_usdt"
        )

    if side == "BUY":
        tp_price = round(price * (1 + tp_pct / 100), 2)
        sl_price = round(price * (1 - sl_pct / 100), 2)
    else:
        tp_price = round(price * (1 - tp_pct / 100), 2)
        sl_price = round(price * (1 + sl_pct / 100), 2)

    order = broker.place_market_order(symbol, side, qty)

    # Persist immediately after the market order lands so that if set_tp_sl
    # fails, reconciliation still sees the live position and can handle it.
    position_data = {
        "side": side,
        "entry_price": price,
        "qty": qty,
        "tp_price": tp_price,
        "sl_price": sl_price,
        "size_usdt": size_usdt,
        "order_id": order["orderId"],
        "opened_at": datetime.utcnow().isoformat(),
    }
    state.save_position(symbol, position_data)

    broker.set_tp_sl(symbol, side, qty, tp_price, sl_price)
    state.log_trade(
        {
            "event": "open",
            "symbol": symbol,
            "side": side,
            "entry_price": price,
            "qty": qty,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "size_usdt": size_usdt,
            "order_id": order["orderId"],
        }
    )

    logger.info("Opened %s position for %s at %s", side, symbol, price)

    return {
        "status": "opened",
        "symbol": symbol,
        "side": side,
        "entry": price,
        "tp": tp_price,
        "sl": sl_price,
        "qty": qty,
    }
