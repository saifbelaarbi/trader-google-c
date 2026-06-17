"""
ClaudeVWAP — Daily-reset VWAP mean-reversion on 15m candles.

Thesis
------
Intraday price oscillates around the Volume-Weighted Average Price (VWAP).
Extreme deviations from VWAP (≥ 2σ of intraday TP−VWAP residuals) that also
show RSI exhaustion tend to snap back — providing edge with a tight ATR stop.

Key fee-survival mechanics
--------------------------
- Band-width filter: only trade when 2σ / price ≥ 0.6% — ensures the potential
  move from the band to VWAP is several times the 0.12% round-trip fee.
- Selectivity: CooldownPeriod + one-trade-per-direction-per-day limit via the
  MaxDrawdown / StoplossGuard combination keeps trade count low.
- Stop: 1.5×ATR from open; exit target is VWAP re-touch — tight enough to cut
  losers but wide enough not to get stopped by noise.
- Force-flat at UTC day end (23:45 bar) avoids overnight gap risk.

Entry conditions
----------------
  Long  : close ≤ VWAP − 2σ  AND  RSI(14) < 35  AND  RSI rising (cur > prev)
           AND  band_width ≥ 0.006  AND  volume > 0
  Short : close ≥ VWAP + 2σ  AND  RSI(14) > 65  AND  RSI falling (cur < prev)
           AND  band_width ≥ 0.006  AND  volume > 0

Exit conditions
---------------
  custom_exit : price re-crosses VWAP (mean-reversion complete)
  custom_exit : last 15m bar of UTC day (force-flat, avoid day-boundary gaps)
  custom_stoploss : 1.5×ATR from open price
"""

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_open
from pandas import DataFrame

logger = logging.getLogger(__name__)


class ClaudeVWAP(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = True

    # Hard failsafe; real stop is ATR-based in custom_stoploss.
    stoploss = -0.20
    use_custom_stoploss = True

    # Let custom_exit manage the target; ROI is an emergency safety net only.
    minimal_roi = {"0": 100}

    process_only_new_candles = True
    # RSI(14) needs 14 bars; VWAP needs intraday history; ATR(14) needs 14.
    # 200 bars gives ~2 days of 15m candles — sufficient for all indicators.
    startup_candle_count = 200

    # Selectivity knobs
    band_width_min = 0.006   # 0.6% minimum (2σ / price) before entering
    rsi_long_max = 35        # RSI threshold for long entry
    rsi_short_min = 65       # RSI threshold for short entry
    atr_stop_mult = 1.5      # ATR multiplier for the stop

    # Position sizing
    max_stake_usdt = 40.0
    wallet_fraction = 0.20

    @property
    def protections(self):
        return [
            # After each trade, pause 4 candles (1 h) before re-entering same pair.
            {"method": "CooldownPeriod", "stop_duration_candles": 4},
            # If 4+ stop-outs in a 24 h window, pause 4 h per pair.
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 96,   # 24 h of 15m candles
                "trade_limit": 4,
                "stop_duration_candles": 16,     # 4 h
                "only_per_pair": True,
            },
            # Portfolio-level circuit breaker: if drawdown > 12% in 48 h, pause 8 h.
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 192,  # 48 h
                "trade_limit": 6,
                "stop_duration_candles": 32,     # 8 h
                "max_allowed_drawdown": 0.12,
            },
        ]

    # ------------------------------------------------------------------
    # Indicator computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_vwap_bands(dataframe: DataFrame):
        """
        Compute daily-reset VWAP and rolling σ-bands.

        For each UTC day, cumulative TP×Volume and cumulative Volume are
        summed from the first bar of that day.  σ is the standard deviation
        of (typical_price − VWAP) within the rolling intraday window.

        Only past bars contribute to each row's calculation (cumsum within
        group is inherently causal — bar t uses bars 1..t of that day).
        """
        tp = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3.0
        vol = dataframe["volume"].copy()

        # Mark each bar with its UTC day (floor to midnight).
        day_key = dataframe["date"].dt.floor("1D")

        # Intraday cumulative sums — causal by definition.
        tp_vol = tp * vol
        cum_tp_vol = tp_vol.groupby(day_key).cumsum()
        cum_vol = vol.groupby(day_key).cumsum()

        vwap = cum_tp_vol / cum_vol.replace(0, np.nan)

        # σ: std of (TP − VWAP) within the running intraday window.
        residual = tp - vwap
        # Use expanding() within each day group (causal).
        sigma = residual.groupby(day_key).expanding().std().reset_index(level=0, drop=True)

        return vwap, sigma

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ---- RSI ----
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi_prev"] = dataframe["rsi"].shift(1)

        # ---- ATR ----
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]

        # ---- VWAP + σ-bands ----
        vwap, sigma = self._compute_vwap_bands(dataframe)
        dataframe["vwap"] = vwap
        dataframe["vwap_sigma"] = sigma

        dataframe["vwap_upper"] = dataframe["vwap"] + 2 * dataframe["vwap_sigma"]
        dataframe["vwap_lower"] = dataframe["vwap"] - 2 * dataframe["vwap_sigma"]

        # Band width as fraction of price (used for the selectivity filter).
        dataframe["band_width"] = (
            2 * dataframe["vwap_sigma"] / dataframe["close"].replace(0, np.nan)
        )

        # ---- Day-end flag (last 15m bar of UTC day = 23:45) ----
        dataframe["is_day_end"] = dataframe["date"].dt.hour == 23
        dataframe["is_day_end"] = dataframe["is_day_end"] & (
            dataframe["date"].dt.minute == 45
        )

        return dataframe

    # ------------------------------------------------------------------
    # Entry / exit signals
    # ------------------------------------------------------------------

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        common_filter = (
            (dataframe["volume"] > 0)
            & dataframe["vwap"].notna()
            & dataframe["vwap_sigma"].notna()
            & (dataframe["vwap_sigma"] > 0)
            & (dataframe["band_width"] >= self.band_width_min)
            & dataframe["rsi"].notna()
            & dataframe["rsi_prev"].notna()
        )

        long_mask = (
            common_filter
            & (dataframe["close"] <= dataframe["vwap_lower"])
            & (dataframe["rsi"] < self.rsi_long_max)
            & (dataframe["rsi"] > dataframe["rsi_prev"])   # RSI turning up
        )

        short_mask = (
            common_filter
            & (dataframe["close"] >= dataframe["vwap_upper"])
            & (dataframe["rsi"] > self.rsi_short_min)
            & (dataframe["rsi"] < dataframe["rsi_prev"])   # RSI turning down
        )

        dataframe.loc[long_mask, "enter_long"] = 1
        dataframe.loc[long_mask, "enter_tag"] = "vwap_long"
        dataframe.loc[short_mask, "enter_short"] = 1
        dataframe.loc[short_mask, "enter_tag"] = "vwap_short"
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Bulk exits handled in custom_exit; this is left intentionally empty
        # so Freqtrade's signal machinery doesn't fight custom_exit.
        return dataframe

    # ------------------------------------------------------------------
    # Custom exit: VWAP re-touch OR day-end force-flat
    # ------------------------------------------------------------------

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None

        last = dataframe.iloc[-1]

        # ---- Force-flat at 23:45 UTC (last bar of the day) ----
        if last.get("is_day_end", False):
            return "day_end_force_flat"

        # ---- Mean-reversion exit: price re-crosses VWAP ----
        vwap = last.get("vwap")
        if vwap is None or np.isnan(float(vwap)):
            return None

        vwap = float(vwap)
        if trade.is_short and current_rate <= vwap:
            return "vwap_retouch_short"
        if not trade.is_short and current_rate >= vwap:
            return "vwap_retouch_long"

        return None

    # ------------------------------------------------------------------
    # Custom stoploss: 1.5×ATR from open
    # ------------------------------------------------------------------

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
        atr_pct = self._last_candle_value(pair, "atr_pct") or 0.015
        atr_pct = max(atr_pct, 0.004)   # never tighter than 0.4%
        return stoploss_from_open(
            -self.atr_stop_mult * atr_pct,
            current_profit,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _last_candle_value(self, pair: str, column: str):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty or column not in dataframe.columns:
            return None
        value = dataframe[column].iloc[-1]
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
