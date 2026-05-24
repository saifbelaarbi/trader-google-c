"""Backward-compatible facade — delegates to the broker selected by BROKER env var.

Existing callers keep using `broker.place_market_order(...)` etc. unchanged.
New code can also call `broker.active()` to access the Broker object directly
(for .supports_short, .manages_tp_sl_natively, .get_open_position, .get_price).
"""

from agent.brokers import get_broker


def active():
    return get_broker()


def place_market_order(symbol: str, side: str, qty: float) -> dict:
    return active().place_market_order(symbol, side, qty)


def set_tp_sl(symbol: str, side: str, qty: float, tp_price: float, sl_price: float,
              tp2_price: float | None = None):
    return active().set_tp_sl(symbol, side, qty, tp_price, sl_price, tp2_price=tp2_price)


def set_trailing_stop(symbol: str, trailing_distance: float,
                      active_price: float | None = None):
    return active().set_trailing_stop(symbol, trailing_distance, active_price)


def close_position(symbol: str):
    return active().close_position(symbol)


def get_open_position(symbol: str):
    return active().get_open_position(symbol)


def get_account_balance() -> float:
    return active().get_balance()
