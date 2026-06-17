"""
ClaudeRSI2 — Connors-style RSI(2) mean-reversion inside the 1h trend.

Thesis
------
RSI(2) is hyper-sensitive: an extreme reading (< 10 or > 90) typically
snaps back within a handful of bars, giving a high hit-rate, short-hold
edge. The catch — and Connors himself emphasised this — is that RSI(2)
fires *very* frequently on raw 15-minute data, and at 0.12% round-trip
fees you need bounces of at least ~0.20% just to break even. Two sources
of overtrading death we saw in earlier strategies (ClaudeConsensus: 6,919
trades at −99.97%; ClaudePullback: PF 0.51) must be avoided here.

Gates added to control overtrading
------------------------------------
1. **1h EMA200 trend filter** (informative): only long when 15m close > EMA200
   on the 1h chart; only short when below. Mean-revert *with* the macro
   trend so we catch dips, not reversals.

2. **Volatility floor** — ATR(14)/close ≥ 0.005: if price barely moves the
   potential bounce is smaller than fees. Skip low-vol noise.

3. **ADX(14) ≥ 20** — need some trend strength. Pure chop with RSI(2) < 10
   can stay oversold for hours; ADX > 20 means there is at least a mild
   directional bias to snap back to.

4. **CooldownPeriod** (4 candles = 1h): suppress re-entering the same dip
   repeatedly in a falling knife.

5. **StoplossGuard**: halt if 3 stop-outs in 72h to protect against choppy
   regime that breaks all other gates.

6. **MaxDrawdown** guard at 12% over 30 days.

Exit logic
----------
- RSI(2) > 60 (longs) / < 40 (shorts): profit-take when reversion is done.
- Optionally, a close back below/above EMA10 also triggers exit.
- Hard stop: 2×ATR(14) via custom_stoploss — prevents a dip becoming a
  disaster if the mean-reversion never comes.

Expectation profile
-------------------
High win-rate (~60-70%), short average holds (2-6 hours), small winners
each clearing >0.12% fees. Profit factor target ≥ 1.2.
"""

import logging
from datetime import datetime
from typing import Optional

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, informative, stoploss_from_open
from pandas import DataFrame

logger = logging.getLogger(__name__)


class ClaudeRSI2(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = True

    # Hard failsafe — real stop is ATR-based in custom_stoploss
    stoploss = -0.20
    use_custom_stoploss = True

    # Let custom_exit / populate_exit_trend manage the exits; no hard ROI cap
    minimal_roi = {"0": 100}

    process_only_new_candles = True
    # 1h EMA200 needs 200 1h candles = 800 15m candles; add buffer
    startup_candle_count = 900

    # --- tunables ---
    rsi2_long_entry = 10    # long when RSI(2) drops below this
    rsi2_short_entry = 90   # short when RSI(2) rises above this
    rsi2_long_exit = 60     # close long when RSI(2) recovers above this
    rsi2_short_exit = 40    # close short when RSI(2) recovers below this
    adx_min = 20            # minimum ADX to trade (some trend needed)
    atr_pct_min = 0.005     # 0.5% ATR/close volatility floor
    atr_stop_mult = 2.0     # stop = atr_stop_mult × ATR from entry

    max_stake_usdt = 40.0
    wallet_fraction = 0.20

    @property
    def protections(self):
        return [
            # Suppress re-entry for 4 × 15m = 1h after any exit
            {"method": "CooldownPeriod", "stop_duration_candles": 4},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 288,  # 3 days of 15m candles
                "trade_limit": 3,
                "stop_duration_candles": 48,     # 12h pause
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 2880,  # 30 days of 15m candles
                "trade_limit": 8,
                "stop_duration_candles": 192,     # 48h pause
                "max_allowed_drawdown": 0.12,
            },
        ]

    # ------------------------------------------------------------------ #
    #  1h informative: EMA200 for trend regime                            #
    # ------------------------------------------------------------------ #
    @informative("1h")
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        return dataframe

    # ------------------------------------------------------------------ #
    #  15m indicators                                                     #
    # ------------------------------------------------------------------ #
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # RSI(2) — hyper-fast mean-reversion trigger
        dataframe["rsi2"] = ta.RSI(dataframe, timeperiod=2)

        # Volatility gate
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]

        # Trend-strength gate (need *some* directionality for a snap-back)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        # Short EMA for optional exit signal
        dataframe["ema10"] = ta.EMA(dataframe, timeperiod=10)

        return dataframe

    # ------------------------------------------------------------------ #
    #  Entry signals                                                      #
    # ------------------------------------------------------------------ #
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        base_gates = (
            (dataframe["volume"] > 0)
            & (dataframe["adx"] >= self.adx_min)
            & (dataframe["atr_pct"] >= self.atr_pct_min)
            & dataframe["ema200_1h"].notna()
        )

        long_mask = (
            base_gates
            & (dataframe["close"] > dataframe["ema200_1h"])  # macro uptrend
            & (dataframe["rsi2"] < self.rsi2_long_entry)     # deep oversold dip
        )

        short_mask = (
            base_gates
            & (dataframe["close"] < dataframe["ema200_1h"])  # macro downtrend
            & (dataframe["rsi2"] > self.rsi2_short_entry)    # deep overbought spike
        )

        dataframe.loc[long_mask, "enter_long"] = 1
        dataframe.loc[long_mask, "enter_tag"] = "rsi2_dip_long"
        dataframe.loc[short_mask, "enter_short"] = 1
        dataframe.loc[short_mask, "enter_tag"] = "rsi2_spike_short"
        return dataframe

    # ------------------------------------------------------------------ #
    #  Exit signals                                                       #
    # ------------------------------------------------------------------ #
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # RSI(2) mean-reversion complete
        dataframe.loc[dataframe["rsi2"] > self.rsi2_long_exit, "exit_long"] = 1
        dataframe.loc[dataframe["rsi2"] < self.rsi2_short_exit, "exit_short"] = 1
        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        """
        Secondary exit: if price closes back through the short EMA after
        entry, the mean-reversion has occurred and we lock in the gain.
        Also acts as a safeguard if RSI(2) exit fires late.
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None
        last = dataframe.iloc[-1]
        ema10 = last.get("ema10")
        close = last.get("close")
        if ema10 is None or close is None:
            return None

        # Long: exit if close crosses above EMA10 (reversion done) *and* we have
        # a non-negative profit (don't exit a losing trade early via this path).
        if not trade.is_short and close > ema10 and current_profit > 0:
            return "ema10_exit_long"

        # Short: exit if close crosses below EMA10 and we are in profit.
        if trade.is_short and close < ema10 and current_profit > 0:
            return "ema10_exit_short"

        return None

    # ------------------------------------------------------------------ #
    #  Position sizing                                                    #
    # ------------------------------------------------------------------ #
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

    # ------------------------------------------------------------------ #
    #  ATR-based stop                                                     #
    # ------------------------------------------------------------------ #
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
        atr_pct = max(atr_pct, self.atr_pct_min)
        stop_pct = self.atr_stop_mult * atr_pct
        return stoploss_from_open(
            -stop_pct, current_profit, is_short=trade.is_short, leverage=trade.leverage
        )

    # ------------------------------------------------------------------ #
    #  Utility                                                            #
    # ------------------------------------------------------------------ #
    def _last_candle_value(self, pair: str, column: str):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty or column not in dataframe.columns:
            return None
        value = dataframe[column].iloc[-1]
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
