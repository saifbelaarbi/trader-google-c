"""Abstract broker interface — all execution venues implement this."""

from abc import ABC, abstractmethod


class Broker(ABC):
    name: str = "base"
    supports_short: bool = True          # can we open SHORT positions?
    manages_tp_sl_natively: bool = True  # does the venue hold TP/SL orders?

    def normalize_symbol(self, symbol: str) -> str:
        """Map internal symbol (BTCUSDT) to venue symbol. Override as needed."""
        return symbol

    @abstractmethod
    def place_market_order(self, symbol: str, side: str, qty: float) -> dict:
        ...

    @abstractmethod
    def close_position(self, symbol: str) -> dict | None:
        ...

    @abstractmethod
    def get_open_position(self, symbol: str) -> dict | None:
        ...

    @abstractmethod
    def get_balance(self) -> float:
        ...

    def set_tp_sl(self, symbol: str, side: str, qty: float,
                  tp_price: float, sl_price: float):
        """Place TP/SL orders. Default no-op for venues that self-manage via bar checks."""
        return None, None

    def get_price(self, symbol: str) -> float:
        raise NotImplementedError
