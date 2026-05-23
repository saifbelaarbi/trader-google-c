"""Binance Futures broker — legacy venue, supports shorts + native TP/SL."""

import logging
import os

from agent.brokers.base import Broker

logger = logging.getLogger(__name__)


class BinanceBroker(Broker):
    name = "binance"
    supports_short = True
    manages_tp_sl_natively = True

    def __init__(self):
        from binance.client import Client

        key = os.environ.get("BINANCE_API_KEY", "")
        secret = os.environ.get("BINANCE_API_SECRET", "")
        testnet = os.environ.get("TRADING_MODE", "testnet").lower() != "live"
        self._client = Client(key, secret, testnet=testnet)
        logger.warning("Binance broker ready (testnet=%s)", testnet)

    def place_market_order(self, symbol: str, side: str, qty: float) -> dict:
        from binance.client import Client
        return self._client.futures_create_order(
            symbol=symbol,
            side=Client.SIDE_BUY if side == "BUY" else Client.SIDE_SELL,
            type=Client.ORDER_TYPE_MARKET,
            quantity=round(qty, 3),
        )

    def set_tp_sl(self, symbol, side, qty, tp_price, sl_price):
        from binance.client import Client
        close_side = Client.SIDE_SELL if side == "BUY" else Client.SIDE_BUY
        tp = self._client.futures_create_order(
            symbol=symbol, side=close_side, type="TAKE_PROFIT_MARKET",
            stopPrice=round(tp_price, 2), closePosition=True,
        )
        sl = self._client.futures_create_order(
            symbol=symbol, side=close_side, type="STOP_MARKET",
            stopPrice=round(sl_price, 2), closePosition=True,
        )
        return tp, sl

    def close_position(self, symbol: str) -> dict | None:
        from binance.client import Client
        positions = self._client.futures_position_information(symbol=symbol)
        open_pos = next((p for p in positions if float(p["positionAmt"]) != 0), None)
        if open_pos is None:
            return None
        pos_amt = float(open_pos["positionAmt"])
        close_side = Client.SIDE_SELL if pos_amt > 0 else Client.SIDE_BUY
        return self._client.futures_create_order(
            symbol=symbol, side=close_side, type=Client.ORDER_TYPE_MARKET,
            quantity=round(abs(pos_amt), 3), reduceOnly=True,
        )

    def get_open_position(self, symbol: str) -> dict | None:
        positions = self._client.futures_position_information(symbol=symbol)
        open_pos = next((p for p in positions if float(p["positionAmt"]) != 0), None)
        if open_pos is None:
            return None
        return {
            "symbol": symbol,
            "qty": float(open_pos["positionAmt"]),
            "entry_price": float(open_pos["entryPrice"]),
        }

    def get_balance(self) -> float:
        account = self._client.futures_account_balance()
        usdt = next((b for b in account if b["asset"] == "USDT"), None)
        return float(usdt["availableBalance"]) if usdt else 0.0

    def get_price(self, symbol: str) -> float:
        t = self._client.futures_symbol_ticker(symbol=symbol)
        return float(t["price"])
