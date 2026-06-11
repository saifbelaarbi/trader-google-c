"""
ClaudeConsensus — Freqtrade port of the 8-point indicator consensus engine
(agent/signals.py), for local paper trading and backtesting on Bybit.

Signal points (each +1, max 8):
  1. EMA20 vs EMA50 on 15m          (trend)
  2. EMA20 vs EMA50 on 1h           (higher-tf trend)
  3. RSI in bull/bear zone          (momentum)
  4. MACD hist sign AND accelerating
  5. Volume ratio > 1.2
  6. EMA20 slope direction
  7. StochRSI K rising from low / falling from high
  8. ADX > 25                       (trend strength)

Market regime (ATR/EMA50 ratio on 1h):
  > 0.015 trending  → normal threshold (5/8) + full size
  < 0.008 ranging   → +1 signal required (6/8), size × 0.6

Exits:
  TP1: partial close 50% at +1×ATR   (adjust_trade_position)
  TP2: full close at +2×ATR          (custom_exit)
  SL : 1×ATR from entry, trails 0.5×ATR once past TP1 (custom_stoploss)
  Consensus flip: ≥3 opposite signals → exit (populate_exit_trend)
"""

from datetime import datetime
from typing import Optional

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, informative, stoploss_from_open
from pandas import DataFrame


class ClaudeConsensus(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = True

    # Hard failsafe only — the real stop is ATR-based in custom_stoploss.
    stoploss = -0.10
    use_custom_stoploss = True

    # ROI disabled — exits are ATR targets + consensus flips.
    minimal_roi = {"0": 100}

    position_adjustment_enable = True  # enables TP1 partial close
    process_only_new_candles = True
    startup_candle_count = 100

    # Risk caps (mirrors agent/config.py + agent/risk.py)
    max_stake_usdt = 40.0
    min_stake_usdt = 15.0

    @property
    def protections(self):
        # Mirrors H2 (daily loss limit) and H4 (anti-whipsaw cooldown).
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 96,  # 24h of 15m candles
                "trade_limit": 3,
                "stop_duration_candles": 24,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 96,
                "trade_limit": 4,
                "stop_duration_candles": 96,
                "max_allowed_drawdown": 0.10,  # ≈ $20 on a $200 wallet
            },
        ]

    @informative("1h")
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd_hist"] = macd["macdhist"]
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["volume"].rolling(20).mean()
        stoch = ta.STOCHRSI(dataframe, timeperiod=14, fastk_period=3, fastd_period=3)
        dataframe["stoch_k"] = stoch["fastk"]
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        # Market regime from 1h ATR/EMA50 ratio (columns merged by @informative)
        regime_ratio = dataframe["atr_1h"] / dataframe["ema50_1h"]
        dataframe["regime_ranging"] = regime_ratio < 0.008
        dataframe["min_signals"] = 5
        dataframe.loc[dataframe["regime_ranging"], "min_signals"] = 6

        bull = [
            dataframe["ema20"] > dataframe["ema50"],
            dataframe["ema20_1h"] > dataframe["ema50_1h"],
            (dataframe["rsi"] > 50) & (dataframe["rsi"] < 72),
            (dataframe["macd_hist"] > 0)
            & (dataframe["macd_hist"] > dataframe["macd_hist"].shift(1)),
            dataframe["vol_ratio"] > 1.2,
            dataframe["ema20"] > dataframe["ema20"].shift(1),
            (dataframe["stoch_k"] > 20) & (dataframe["stoch_k"] > dataframe["stoch_k"].shift(1)),
            dataframe["adx"] > 25,
        ]
        bear = [
            dataframe["ema20"] < dataframe["ema50"],
            dataframe["ema20_1h"] < dataframe["ema50_1h"],
            (dataframe["rsi"] > 28) & (dataframe["rsi"] < 50),
            (dataframe["macd_hist"] < 0)
            & (dataframe["macd_hist"] < dataframe["macd_hist"].shift(1)),
            dataframe["vol_ratio"] > 1.2,
            dataframe["ema20"] < dataframe["ema20"].shift(1),
            (dataframe["stoch_k"] < 80) & (dataframe["stoch_k"] < dataframe["stoch_k"].shift(1)),
            dataframe["adx"] > 25,
        ]
        dataframe["bull_count"] = sum(cond.fillna(False).astype(int) for cond in bull)
        dataframe["bear_count"] = sum(cond.fillna(False).astype(int) for cond in bear)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_mask = (dataframe["bull_count"] >= dataframe["min_signals"]) & (
            dataframe["volume"] > 0
        )
        short_mask = (dataframe["bear_count"] >= dataframe["min_signals"]) & (
            dataframe["volume"] > 0
        )
        dataframe.loc[long_mask, "enter_long"] = 1
        dataframe.loc[long_mask, "enter_tag"] = (
            "bull_" + dataframe.loc[long_mask, "bull_count"].astype(str)
        )
        dataframe.loc[short_mask, "enter_short"] = 1
        dataframe.loc[short_mask, "enter_tag"] = (
            "bear_" + dataframe.loc[short_mask, "bear_count"].astype(str)
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Consensus flip — same threshold as agent/signals.py CLOSE logic.
        dataframe.loc[dataframe["bear_count"] >= 3, "exit_long"] = 1
        dataframe.loc[dataframe["bull_count"] >= 3, "exit_short"] = 1
        return dataframe

    # ── Position sizing — scales with signal confidence, regime-adjusted ──────

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        score = 5
        if entry_tag and "_" in entry_tag:
            try:
                score = int(entry_tag.split("_")[1])
            except ValueError:
                pass
        confidence = score / 8.0
        stake = self.max_stake_usdt * (0.5 + 0.5 * max(0.0, confidence - 0.5) / 0.5)
        if self._last_candle_value(pair, "regime_ranging"):
            stake *= 0.6
        stake = max(self.min_stake_usdt, min(stake, self.max_stake_usdt))
        if min_stake:
            stake = max(stake, min_stake)
        return min(stake, max_stake)

    def leverage(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        return 1.0

    # ── ATR stop: 1×ATR from entry, trail 0.5×ATR once past TP1 ──────────────

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> Optional[float]:
        atr_pct = self._last_candle_value(pair, "atr_pct") or 0.005
        atr_pct = max(atr_pct, 0.001)
        if current_profit < atr_pct:
            # Hold initial stop at entry − 1×ATR (stop never widens in freqtrade)
            return stoploss_from_open(
                -atr_pct, current_profit, is_short=trade.is_short, leverage=trade.leverage
            )
        # Past TP1 → trail 0.5×ATR behind price
        return -(0.5 * atr_pct)

    # ── TP1: close 50% at +1×ATR ──────────────────────────────────────────────

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: Optional[float],
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ) -> Optional[float]:
        if trade.nr_of_successful_exits > 0:
            return None
        atr_pct = self._last_candle_value(pair=trade.pair, column="atr_pct") or 0.005
        if current_profit >= atr_pct:
            return -(trade.stake_amount * 0.5)
        return None

    # ── TP2: full exit at +2×ATR ──────────────────────────────────────────────

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        atr_pct = self._last_candle_value(pair, "atr_pct") or 0.005
        if current_profit >= 2 * atr_pct:
            return "tp2_2xatr"
        return None

    # ── helpers ────────────────────────────────────────────────────────────────

    def _last_candle_value(self, pair: str, column: str):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty or column not in dataframe.columns:
            return None
        value = dataframe[column].iloc[-1]
        try:
            return float(value)
        except (TypeError, ValueError):
            return bool(value)
