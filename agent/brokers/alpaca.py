"""Alpaca broker — crypto SPOT, long-only, paper or live.

Crypto on Alpaca has no shorting and no leverage, so supports_short=False.
Alpaca crypto has no server-side bracket TP/SL, so we self-manage TP/SL by
checking each new bar in the auto-executor (manages_tp_sl_natively=False).
"""

import logging
import os

from agent.brokers.base import Broker

logger = logging.getLogger(__name__)


class AlpacaBroker(Broker):
    name = "alpaca"
    supports_short = False
    manages_tp_sl_natively = False

    def __init__(self):
        from alpaca.trading.client import TradingClient

        key = os.environ["ALPACA_API_KEY"]
        secret = os.environ["ALPACA_API_SECRET"]
        paper = os.environ.get("TRADING_MODE", "testnet").lower() != "live"
        self._client = TradingClient(key, secret, paper=paper)
        logger.warning("Alpaca broker ready (paper=%s)", paper)

    def normalize_symbol(self, symbol: str) -> str:
        s = symbol.upper()
        for quote in ("USDT", "USD"):
            if s.endswith(quote):
                return f"{s[:-len(quote)]}/USD"
        return symbol

    def place_market_order(self, symbol: str, side: str, qty: float) -> dict:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        sym = self.normalize_symbol(symbol)
        order_side = OrderSide.BUY if side == "BUY" else OrderSide.SELL
        req = MarketOrderRequest(
            symbol=sym, qty=qty, side=order_side, time_in_force=TimeInForce.GTC
        )
        o = self._client.submit_order(req)
        return {"orderId": str(o.id), "symbol": sym, "qty": qty}

    def close_position(self, symbol: str) -> dict | None:
        sym = self.normalize_symbol(symbol)
        try:
            o = self._client.close_position(sym)
            return {"orderId": str(getattr(o, "id", "closed"))}
        except Exception as exc:
            logger.warning("Alpaca close_position %s: %s", sym, exc)
            return None

    def get_open_position(self, symbol: str) -> dict | None:
        sym = self.normalize_symbol(symbol)
        try:
            p = self._client.get_open_position(sym)
            return {
                "symbol": symbol,
                "qty": float(p.qty),
                "entry_price": float(p.avg_entry_price),
            }
        except Exception:
            return None

    def get_balance(self) -> float:
        acct = self._client.get_account()
        return float(acct.cash)

    def get_price(self, symbol: str) -> float:
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoLatestQuoteRequest

        sym = self.normalize_symbol(symbol)
        dc = CryptoHistoricalDataClient()
        q = dc.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=sym))
        return float(q[sym].ask_price)
