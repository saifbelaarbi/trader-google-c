"""
ClaudeTrend1h — V3: the V2 pullback premise moved from 15m to 1h/4h.

Why: V2 (ClaudePullback, 15m) improved every diagnostic vs V1 (win rate
22%→44%, trades -36%, drawdown slower) but still lost (PF 0.51) because the
fee math on 15m cannot close: avg gross win ~0.3% vs ~0.12% round-trip fees
(~$90 of the $153 loss was fees). 23 of 25 months landed at PF 0.3-0.7 —
a near-zero-edge signal ground down by costs, not a tunable parameter.

V3 isolates the timeframe/fee variable: identical premise, 1h entries with
4h trend filter. ATR(1h) targets are ~2%, so fees drop from ~40% of a win
to ~6%, and trade count drops ~10×.

Entry (long; short is the mirror):
  - EMA20 > EMA50 on 1h AND 4h       (established trend, both timeframes)
  - ADX > 20                          (trend has strength)
  - close at/below EMA20 (+0.2%)      (pullback into value)
  - StochRSI K < 40 and turning up    (dip exhausted)
  - RSI > 35                          (pullback, not breakdown)

Exits:
  SL   : 2×ATR(1h) from entry; trails 1×ATR once profit ≥ 2×ATR
  Trend: confirmed 1h EMA20/EMA50 flip → exit

Decision rule agreed with the user: if this is still clearly below PF 1.0,
the indicator premise is dead — change strategy family, don't tune knobs.
"""

from datetime import datetime
from typing import Optional

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, informative, stoploss_from_open
from pandas import DataFrame


class ClaudeTrend1h(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = True

    # Hard failsafe only — the real stop is ATR-based in custom_stoploss.
    stoploss = -0.15
    use_custom_stoploss = True

    minimal_roi = {"0": 100}

    process_only_new_candles = True
    startup_candle_count = 120

    max_stake_usdt = 40.0
    wallet_fraction = 0.20

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 48,  # 2 days of 1h candles
                "trade_limit": 3,
                "stop_duration_candles": 12,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 168,  # 1 week
                "trade_limit": 4,
                "stop_duration_candles": 48,
                "max_allowed_drawdown": 0.12,
            },
        ]

    @informative("4h")
    def populate_indicators_4h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
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
            & (dataframe["ema20_4h"] > dataframe["ema50_4h"])
            & (dataframe["adx"] > 20)
            & (dataframe["close"] <= dataframe["ema20"] * 1.002)
            & (dataframe["stoch_k"] < 40)
            & (dataframe["stoch_k"] > dataframe["stoch_k"].shift(1))
            & (dataframe["rsi"] > 35)
            & (dataframe["volume"] > 0)
        )
        short_mask = (
            (dataframe["ema20"] < dataframe["ema50"])
            & (dataframe["ema20_4h"] < dataframe["ema50_4h"])
            & (dataframe["adx"] > 20)
            & (dataframe["close"] >= dataframe["ema20"] * 0.998)
            & (dataframe["stoch_k"] > 60)
            & (dataframe["stoch_k"] < dataframe["stoch_k"].shift(1))
            & (dataframe["rsi"] < 65)
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[long_mask, "enter_long"] = 1
        dataframe.loc[long_mask, "enter_tag"] = "pullback_long_1h"
        dataframe.loc[short_mask, "enter_short"] = 1
        dataframe.loc[short_mask, "enter_tag"] = "pullback_short_1h"
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Structural exit only: the 1h trend that justified the entry is gone.
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
        atr_pct = self._last_candle_value(pair, "atr_pct") or 0.01
        atr_pct = max(atr_pct, 0.002)
        if current_profit >= 2 * atr_pct:
            # In profit past 2×ATR → trail 1×ATR behind price (locks ≥ 1×ATR).
            return -atr_pct
        # Initial stop: 2×ATR from entry.
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
