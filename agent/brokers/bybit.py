"""Bybit broker — USDT perpetual futures, supports shorts + native TP/SL."""

import logging
import math
import os

from agent.brokers.base import Broker

logger = logging.getLogger(__name__)

_qty_step_cache: dict[str, float] = {}


class BybitBroker(Broker):
    name = "bybit"
    supports_short = True
    manages_tp_sl_natively = True

    def __init__(self):
        from pybit.unified_trading import HTTP

        testnet = os.environ.get("TRADING_MODE", "testnet").lower() != "live"
        self._client = HTTP(
            testnet=testnet,
            api_key=os.environ["BYBIT_API_KEY"],
            api_secret=os.environ["BYBIT_API_SECRET"],
        )
        logger.warning("Bybit broker ready (testnet=%s)", testnet)

    def _qty_step(self, symbol: str) -> float:
        if symbol not in _qty_step_cache:
            r = self._client.get_instruments_info(category="linear", symbol=symbol)
            lst = r["result"]["list"]
            step = float(lst[0]["lotSizeFilter"]["qtyStep"]) if lst else 0.001
            _qty_step_cache[symbol] = step
        return _qty_step_cache[symbol]

    def _round_qty(self, symbol: str, qty: float) -> float:
        step = self._qty_step(symbol)
        precision = max(0, -int(math.floor(math.log10(step))))
        return round(round(qty / step) * step, precision)

    def place_market_order(self, symbol: str, side: str, qty: float) -> dict:
        qty = self._round_qty(symbol, qty)
        r = self._client.place_order(
            category="linear", symbol=symbol,
            side="Buy" if side == "BUY" else "Sell",
            orderType="Market", qty=str(qty),
        )
        return {"orderId": r["result"]["orderId"], "symbol": symbol, "qty": qty}

    def set_tp_sl(self, symbol, side, qty, tp_price, sl_price):
        self._client.set_trading_stop(
            category="linear", symbol=symbol,
            takeProfit=str(tp_price), stopLoss=str(sl_price), positionIdx=0,
        )
        return tp_price, sl_price

    def close_position(self, symbol: str) -> dict | None:
        pos = self.get_open_position(symbol)
        if not pos:
            return None
        close_side = "Sell" if pos["qty"] > 0 else "Buy"
        r = self._client.place_order(
            category="linear", symbol=symbol, side=close_side,
            orderType="Market", qty=str(abs(pos["qty"])), reduceOnly=True,
        )
        return {"orderId": r["result"]["orderId"]}

    def get_open_position(self, symbol: str) -> dict | None:
        r = self._client.get_positions(category="linear", symbol=symbol)
        lst = r["result"]["list"]
        if not lst or float(lst[0]["size"]) == 0:
            return None
        p = lst[0]
        size = float(p["size"])
        qty = size if p["side"] == "Buy" else -size
        return {"symbol": symbol, "qty": qty, "entry_price": float(p["avgPrice"])}

    def get_balance(self) -> float:
        r = self._client.get_wallet_balance(accountType="UNIFIED")
        return float(r["result"]["list"][0]["totalAvailableBalance"])

    def get_price(self, symbol: str) -> float:
        r = self._client.get_tickers(category="linear", symbol=symbol)
        return float(r["result"]["list"][0]["lastPrice"])
