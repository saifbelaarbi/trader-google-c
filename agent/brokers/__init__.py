"""Broker factory — selects venue via BROKER env var (alpaca|bybit|binance)."""

import os

_cache: dict = {}


def get_broker(name: str | None = None):
    name = (name or os.environ.get("BROKER", "bybit")).lower()
    if name in _cache:
        return _cache[name]

    if name == "alpaca":
        from agent.brokers.alpaca import AlpacaBroker
        broker = AlpacaBroker()
    elif name == "bybit":
        from agent.brokers.bybit import BybitBroker
        broker = BybitBroker()
    elif name == "binance":
        from agent.brokers.binance import BinanceBroker
        broker = BinanceBroker()
    else:
        raise ValueError(f"Unknown broker: {name}")

    _cache[name] = broker
    return broker
