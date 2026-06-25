"""
ClaudeDayTrader — V-next, synthesized from the 6-way fast-day-trading bake-off.

Bake-off result (15m candidates, 2024-06 → 2026-06, same data + 0.06% taker fee):
  ClaudeDonchian15m  PF 0.95   (4293 trades)  ← best; breakout edge, killed only by fees
  ClaudeRSI2         PF 0.73   (10331 trades) — fee death (over-trading)
  ClaudeVWAP         PF 0.69   (8255 trades)  — fee death (over-trading)
  ClaudeMomoScalp    PF 0.22   (2033 trades)  — broken edge
  ClaudeORB          ~0 trades — n/a
  ClaudeSqueeze      bug (not scored)

Lesson confirmed for the 3rd time: 15m trading loses to ~0.12% round-trip fees.
The ONLY edge that works in this repo is the Donchian breakout — at 4h it returns
+38.7% (PF 1.14, ClaudeBreakout). ClaudeDonchian15m showed that same breakout edge
is real even at 15m (PF 0.95) and fails ONLY on trade frequency / fee drag.

Synthesis: run the proven breakout edge at 1h. Fast enough to be intraday — entries
break a 20-bar (≈20h) channel and exit on a 10-bar (≈10h) reversal, so holds are
hours, not the 4h version's multi-day swings — but ~4× fewer trades than 15m, so the
gross breakout edge clears fees. 4h EMA200 macro filter (only trade with the higher-
timeframe trend); 2×ATR disaster stop; Donchian channel trails winners; a volatility
floor skips low-ATR chop where fees dominate.

This is the same machinery as ClaudeBreakout, moved from 4h → 1h with a 4h trend
filter — a deliberate timeframe step between the dead 15m candidates and the winning
4h swing, targeting the "fast money that still clears fees" sweet spot.
"""

from datetime import datetime
from typing import Optional

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, informative, stoploss_from_open
from pandas import DataFrame


class ClaudeDayTrader(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = True

    # Hard failsafe only — the real stop is ATR-based in custom_stoploss.
    stoploss = -0.20
    use_custom_stoploss = True

    minimal_roi = {"0": 100}

    process_only_new_candles = True
    startup_candle_count = 850  # 4h EMA200 needs ~200×4h = 800×1h of warm-up

    entry_window = 20  # ~20h channel — the breakout trigger
    exit_window = 10  # ~10h channel — the trailing exit (winners run intraday)
    atr_floor = 0.004  # skip chop where the move can't clear fees

    max_stake_usdt = 40.0
    wallet_fraction = 0.20

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 168,  # 1 week of 1h candles
                "trade_limit": 4,
                "stop_duration_candles": 24,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 720,  # 30 days of 1h candles
                "trade_limit": 6,
                "stop_duration_candles": 48,
                "max_allowed_drawdown": 0.15,
            },
        ]

    @informative("4h")
    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        # Donchian channels, shifted so the current candle can break the prior window.
        dataframe["dc_entry_high"] = dataframe["high"].rolling(self.entry_window).max().shift(1)
        dataframe["dc_entry_low"] = dataframe["low"].rolling(self.entry_window).min().shift(1)
        dataframe["dc_exit_high"] = dataframe["high"].rolling(self.exit_window).max().shift(1)
        dataframe["dc_exit_low"] = dataframe["low"].rolling(self.exit_window).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_mask = (
            (dataframe["close"] > dataframe["dc_entry_high"])
            & (dataframe["close"] > dataframe["ema200_4h"])
            & (dataframe["atr_pct"] > self.atr_floor)
            & (dataframe["volume"] > 0)
        )
        short_mask = (
            (dataframe["close"] < dataframe["dc_entry_low"])
            & (dataframe["close"] < dataframe["ema200_4h"])
            & (dataframe["atr_pct"] > self.atr_floor)
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[long_mask, "enter_long"] = 1
        dataframe.loc[long_mask, "enter_tag"] = "breakout_long"
        dataframe.loc[short_mask, "enter_short"] = 1
        dataframe.loc[short_mask, "enter_tag"] = "breakout_short"
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Turtle exit: opposite 10-bar extreme — trails winners through the move.
        dataframe.loc[dataframe["close"] < dataframe["dc_exit_low"], "exit_long"] = 1
        dataframe.loc[dataframe["close"] > dataframe["dc_exit_high"], "exit_short"] = 1
        return dataframe

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
        total_equity = self.wallets.get_total_stake_amount() if self.wallets else 200.0
        stake = min(self.max_stake_usdt, total_equity * self.wallet_fraction)
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
        atr_pct = self._last_candle_value(pair, "atr_pct") or 0.02
        atr_pct = max(atr_pct, 0.005)
        # Fixed 2×ATR disaster stop; the Donchian exit manages winners.
        return stoploss_from_open(
            -2 * atr_pct, current_profit, is_short=trade.is_short, leverage=trade.leverage
        )

    def _last_candle_value(self, pair: str, column: str):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty or column not in dataframe.columns:
            return None
        value = dataframe[column].iloc[-1]
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
