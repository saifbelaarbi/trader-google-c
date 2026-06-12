"""
ClaudePullback — V2 strategy, redesigned from the ClaudeConsensus backtest
(2024-06 → 2026-06: -96.79%, PF 0.39, 3413 trades).

Measured leaks in V1 and the V2 response:

  V1 leak                                          V2 change
  ------------------------------------------------ --------------------------------
  ~$127 of $194 loss was fees (3413 trades)        pullback entries → far fewer trades
  1451 stop-outs, 0% winners, 6 min avg duration   stop widened to 2×ATR
  8/8 consensus won 12% vs 5/8 won 27% — entries   enter on pullback to EMA20 in an
  fired at max momentum extension (tops)           established trend, not on extension
  consensus-flip exit won 4.6% (vol/ADX counted    exit only on confirmed 15m EMA
  toward both directions)                          trend flip
  account churned below min stake by Sept 2024     stake = 20% of equity, capped $40
  partial TP1 doubled fee events, capped winners   removed — single position, trail

Entry (long; short is the mirror):
  - EMA20 > EMA50 on 15m AND 1h      (established trend, both timeframes)
  - ADX > 20                          (trend has strength)
  - close at/below EMA20 (+0.2%)      (pullback into value, not extension)
  - StochRSI K < 35 and turning up    (dip exhausted, momentum resuming)
  - RSI > 35                          (pullback, not a breakdown)

Exits:
  SL   : 2×ATR from entry; trails 1×ATR once profit ≥ 1.5×ATR
  Trend: confirmed 15m EMA20/EMA50 flip → exit
"""

from datetime import datetime
from typing import Optional

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, informative, stoploss_from_open
from pandas import DataFrame


class ClaudePullback(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = True

    # Hard failsafe only — the real stop is ATR-based in custom_stoploss.
    stoploss = -0.10
    use_custom_stoploss = True

    # ROI disabled — exits are the ATR trail + trend-flip signal.
    minimal_roi = {"0": 100}

    process_only_new_candles = True
    startup_candle_count = 120

    max_stake_usdt = 40.0
    wallet_fraction = 0.20  # stake scales with equity so drawdowns shrink size

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 4},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 96,
                "trade_limit": 3,
                "stop_duration_candles": 24,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 96,
                "trade_limit": 4,
                "stop_duration_candles": 96,
                "max_allowed_drawdown": 0.10,
            },
        ]

    @informative("1h")
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        stoch = ta.STOCHRSI(dataframe, timeperiod=14, fastk_period=3, fastd_period=3)
        dataframe["stoch_k"] = stoch["fastk"]
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_mask = (
            (dataframe["ema20"] > dataframe["ema50"])
            & (dataframe["ema20_1h"] > dataframe["ema50_1h"])
            & (dataframe["adx"] > 20)
            & (dataframe["close"] <= dataframe["ema20"] * 1.002)
            & (dataframe["stoch_k"] < 35)
            & (dataframe["stoch_k"] > dataframe["stoch_k"].shift(1))
            & (dataframe["rsi"] > 35)
            & (dataframe["volume"] > 0)
        )
        short_mask = (
            (dataframe["ema20"] < dataframe["ema50"])
            & (dataframe["ema20_1h"] < dataframe["ema50_1h"])
            & (dataframe["adx"] > 20)
            & (dataframe["close"] >= dataframe["ema20"] * 0.998)
            & (dataframe["stoch_k"] > 65)
            & (dataframe["stoch_k"] < dataframe["stoch_k"].shift(1))
            & (dataframe["rsi"] < 65)
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[long_mask, "enter_long"] = 1
        dataframe.loc[long_mask, "enter_tag"] = "pullback_long"
        dataframe.loc[short_mask, "enter_short"] = 1
        dataframe.loc[short_mask, "enter_tag"] = "pullback_short"
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Structural exit only: the trend that justified the entry no longer exists.
        dataframe.loc[dataframe["ema20"] < dataframe["ema50"], "exit_long"] = 1
        dataframe.loc[dataframe["ema20"] > dataframe["ema50"], "exit_short"] = 1
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
        atr_pct = self._last_candle_value(pair, "atr_pct") or 0.005
        atr_pct = max(atr_pct, 0.001)
        if current_profit >= 1.5 * atr_pct:
            # In profit past 1.5×ATR → trail 1×ATR behind price.
            return -atr_pct
        # Initial stop: 2×ATR from entry, outside the 15m noise band.
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
