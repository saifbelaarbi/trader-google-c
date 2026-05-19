import logging
import os

from binance.client import Client
from binance.exceptions import BinanceAPIException

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> Client:
    global _client
    if _client is None:
        api_key = os.environ.get("BINANCE_API_KEY", "")
        api_secret = os.environ.get("BINANCE_API_SECRET", "")
        mode = os.environ.get("TRADING_MODE", "testnet")
        if mode == "testnet":
            logger.warning("RUNNING ON BINANCE TESTNET — NO REAL MONEY")
            _client = Client(api_key, api_secret, testnet=True)
        else:
            logger.warning("LIVE TRADING ACTIVE")
            _client = Client(api_key, api_secret)
    return _client


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except BinanceAPIException as e:
        logger.error("Binance API error %s: %s", e.code, e.message)
        raise


def place_market_order(symbol: str, side: str, qty: float) -> dict:
    client = _get_client()
    binance_side = Client.SIDE_BUY if side == "BUY" else Client.SIDE_SELL
    return _call(
        client.futures_create_order,
        symbol=symbol,
        side=binance_side,
        type=Client.ORDER_TYPE_MARKET,
        quantity=round(qty, 6),
    )


def set_tp_sl(
    symbol: str, side: str, qty: float, tp_price: float, sl_price: float
) -> tuple[dict, dict]:
    client = _get_client()
    close_side = Client.SIDE_SELL if side == "BUY" else Client.SIDE_BUY

    tp_order = _call(
        client.futures_create_order,
        symbol=symbol,
        side=close_side,
        type="TAKE_PROFIT_MARKET",
        stopPrice=round(tp_price, 2),
        closePosition=True,
    )
    sl_order = _call(
        client.futures_create_order,
        symbol=symbol,
        side=close_side,
        type="STOP_MARKET",
        stopPrice=round(sl_price, 2),
        closePosition=True,
    )
    return tp_order, sl_order


def close_position(symbol: str) -> dict | None:
    client = _get_client()
    positions = _call(client.futures_position_information, symbol=symbol)
    open_pos = next((p for p in positions if float(p["positionAmt"]) != 0), None)
    if open_pos is None:
        logger.warning("No open position found for %s on Binance", symbol)
        return None
    pos_amt = float(open_pos["positionAmt"])
    close_side = Client.SIDE_SELL if pos_amt > 0 else Client.SIDE_BUY
    return _call(
        client.futures_create_order,
        symbol=symbol,
        side=close_side,
        type=Client.ORDER_TYPE_MARKET,
        quantity=round(abs(pos_amt), 6),
        reduceOnly=True,
    )


def get_account_balance() -> float:
    account = _call(_get_client().futures_account_balance)
    usdt = next((b for b in account if b["asset"] == "USDT"), None)
    return float(usdt["availableBalance"]) if usdt else 0.0
