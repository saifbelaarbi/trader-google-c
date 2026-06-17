"""
ClaudeORB — Opening Range Breakout on 15m candles.

Thesis:
  Each UTC day, the first 8 bars (00:00–01:45 UTC, roughly a 2-hour opening
  range) define OR_high and OR_low. Once that range is set (bar 9 onward), we
  trade breakouts from it:
    LONG  when a bar closes above OR_high
    SHORT when a bar closes below OR_low
  At most one entry per direction per calendar day. By EOD (last 15m bar,
  23:45 UTC) we force-flat via custom_exit → "eod".

Fee-clearing filters (round-trip ≈ 0.12 % on Bybit futures):
  1. Range width ≥ 0.6 % of price   — skip dead/compressed days
  2. Breakout bar volume > 1.3× its 20-bar rolling mean — real participation
  3. ATR(14) > 0.003 × close        — avoid zero-volatility gaps
  Stop: 1.5 × ATR(14) from entry.
  Profit target: OR-height projected from the breakout level (≥ ~0.6 % target).

Lookahead safety:
  OR_high/OR_low are computed only from the FIRST 8 bars of the day and then
  *forward-filled* across the rest of the day. Because populate_indicators
  processes the whole DataFrame at once, we avoid any group-level forward
  reference by computing a `bar_in_day` counter and masking: the OR columns
  are NaN for bar 0–7 and valid from bar 8 onward. No shift() of the signal
  is needed beyond what groupby/cummax gives us.
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


class ClaudeORB(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = True

    # Hard failsafe — real stop is ATR-based via custom_stoploss.
    stoploss = -0.20
    use_custom_stoploss = True

    # ROI disabled — EOD exit + ATR stop handle exits.
    minimal_roi = {"0": 100}

    process_only_new_candles = True
    # ATR(14) + 20-bar volume average + at least 2 full days of history.
    startup_candle_count = 200

    # Strategy parameters (tunable)
    or_bars = 8               # first N 15m bars define the opening range (2h)
    range_min_pct = 0.006     # range width must be ≥ 0.6 % of price
    vol_ratio_min = 1.3       # breakout bar volume vs 20-bar mean
    atr_mult_stop = 1.5       # ATR multiplier for the stop
    atr_min_pct = 0.003       # minimum ATR size (filter near-zero volatility)

    max_stake_usdt = 40.0
    wallet_fraction = 0.20

    # ------------------------------------------------------------------ #
    #  Protections tuned for 15m (96 candles ≈ 24 h)                     #
    # ------------------------------------------------------------------ #
    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 4},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 96,   # 24h of 15m
                "trade_limit": 4,
                "stop_duration_candles": 16,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 672,  # 7 days of 15m
                "trade_limit": 6,
                "stop_duration_candles": 96,
                "max_allowed_drawdown": 0.15,
            },
        ]

    # ------------------------------------------------------------------ #
    #  Indicators                                                          #
    # ------------------------------------------------------------------ #
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # --- Volatility / volume ---
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        dataframe["vol_ma20"] = dataframe["volume"].rolling(20).mean()
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["vol_ma20"]

        # --- Day grouping (UTC) ---
        # date column is UTC-aware; floor to day so each UTC calendar day
        # gets its own group key.
        dataframe["_day"] = dataframe["date"].dt.floor("1D")

        # bar_in_day: 0, 1, 2, … restarted each UTC midnight.
        dataframe["bar_in_day"] = dataframe.groupby("_day").cumcount()

        # --- Opening-range high / low (NO lookahead) ---
        # For each bar, OR = max/min of high/low within the SAME day *up to
        # and including the current bar*, capped to bar_in_day < or_bars.
        # We only expose these values from bar `or_bars` onward, so the
        # range is fully formed before any signal fires.

        # Step 1: zero-out high/low for bars AFTER the opening range window.
        dataframe["_or_high_cand"] = np.where(
            dataframe["bar_in_day"] < self.or_bars,
            dataframe["high"],
            np.nan,
        )
        dataframe["_or_low_cand"] = np.where(
            dataframe["bar_in_day"] < self.or_bars,
            dataframe["low"],
            np.nan,
        )

        # Step 2: running cumulative max/min within each day.
        # groupby + cummax gives the running max of the candidate column,
        # which equals the OR-high once bar_in_day reaches or_bars-1.
        dataframe["_or_high_raw"] = (
            dataframe.groupby("_day")["_or_high_cand"].cummax()
        )
        dataframe["_or_low_raw"] = (
            dataframe.groupby("_day")["_or_low_cand"].cummin()
        )

        # Step 3: only valid from bar `or_bars` onward (range is complete).
        # Use NaN for earlier bars so entry conditions cannot fire.
        valid_mask = dataframe["bar_in_day"] >= self.or_bars
        dataframe["or_high"] = np.where(valid_mask, dataframe["_or_high_raw"], np.nan)
        dataframe["or_low"] = np.where(valid_mask, dataframe["_or_low_raw"], np.nan)

        # Range width (%)
        dataframe["or_range_pct"] = (
            (dataframe["or_high"] - dataframe["or_low"]) / dataframe["or_low"]
        )

        # --- One-entry-per-day gate ---
        # Mark bars where a long/short entry *could* fire, then track whether
        # one already fired earlier in the day. We use a shift(1) trick:
        # the first valid breakout bar per day is allowed; subsequent ones
        # are blocked by a within-day cumulative flag.

        # Preliminary breakout masks (no daily-uniqueness filter yet).
        _pre_long = (
            (dataframe["close"] > dataframe["or_high"])
            & valid_mask
            & (dataframe["or_range_pct"] >= self.range_min_pct)
            & (dataframe["vol_ratio"] >= self.vol_ratio_min)
            & (dataframe["atr_pct"] >= self.atr_min_pct)
        )
        _pre_short = (
            (dataframe["close"] < dataframe["or_low"])
            & valid_mask
            & (dataframe["or_range_pct"] >= self.range_min_pct)
            & (dataframe["vol_ratio"] >= self.vol_ratio_min)
            & (dataframe["atr_pct"] >= self.atr_min_pct)
        )

        # Within each day, has a qualifying long already fired on a PRIOR bar?
        # cumsum().shift(1) counts prior fires within the same group.
        dataframe["_long_fired"] = (
            _pre_long.astype(int)
            .groupby(dataframe["_day"])
            .cumsum()
            .shift(1)
            .fillna(0)
        )
        dataframe["_short_fired"] = (
            _pre_short.astype(int)
            .groupby(dataframe["_day"])
            .cumsum()
            .shift(1)
            .fillna(0)
        )

        # Clean up temporaries
        dataframe.drop(
            columns=["_or_high_cand", "_or_low_cand", "_or_high_raw", "_or_low_raw"],
            inplace=True,
        )

        return dataframe

    # ------------------------------------------------------------------ #
    #  Entry                                                               #
    # ------------------------------------------------------------------ #
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_mask = (
            (dataframe["close"] > dataframe["or_high"])
            & (dataframe["bar_in_day"] >= self.or_bars)
            & (dataframe["or_range_pct"] >= self.range_min_pct)
            & (dataframe["vol_ratio"] >= self.vol_ratio_min)
            & (dataframe["atr_pct"] >= self.atr_min_pct)
            & (dataframe["_long_fired"] == 0)
            & (dataframe["volume"] > 0)
        )
        short_mask = (
            (dataframe["close"] < dataframe["or_low"])
            & (dataframe["bar_in_day"] >= self.or_bars)
            & (dataframe["or_range_pct"] >= self.range_min_pct)
            & (dataframe["vol_ratio"] >= self.vol_ratio_min)
            & (dataframe["atr_pct"] >= self.atr_min_pct)
            & (dataframe["_short_fired"] == 0)
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[long_mask, "enter_long"] = 1
        dataframe.loc[long_mask, "enter_tag"] = "orb_long"
        dataframe.loc[short_mask, "enter_short"] = 1
        dataframe.loc[short_mask, "enter_tag"] = "orb_short"

        return dataframe

    # ------------------------------------------------------------------ #
    #  Exit (signal-based) — EOD exit is in custom_exit                   #
    # ------------------------------------------------------------------ #
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # No signal-based exit here; custom_exit handles EOD flat.
        # The ATR stop (custom_stoploss) handles adverse moves.
        # OR-height profit target is also in custom_exit.
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe

    # ------------------------------------------------------------------ #
    #  Custom exit — EOD flat + OR-height profit target                   #
    # ------------------------------------------------------------------ #
    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        # EOD: force flat on the last 15m bar of each UTC day (23:45).
        if current_time.hour == 23 and current_time.minute >= 45:
            return "eod"

        # OR-height profit target:
        #   LONG  target = entry + (or_high - or_low)
        #   SHORT target = entry - (or_high - or_low)
        or_high = self._last_candle_value(pair, "or_high")
        or_low = self._last_candle_value(pair, "or_low")
        if or_high is None or or_low is None:
            return None

        or_height = or_high - or_low
        if or_height <= 0:
            return None

        if not trade.is_short:
            target = trade.open_rate + or_height
            if current_rate >= target:
                return "or_target_long"
        else:
            target = trade.open_rate - or_height
            if current_rate <= target:
                return "or_target_short"

        return None

    # ------------------------------------------------------------------ #
    #  Custom stoploss — 1.5 × ATR from open                             #
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
        atr_pct = self._last_candle_value(pair, "atr_pct") or 0.015
        atr_pct = max(atr_pct, 0.005)
        return stoploss_from_open(
            -self.atr_mult_stop * atr_pct,
            current_profit,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )

    # ------------------------------------------------------------------ #
    #  Stake sizing                                                        #
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
    #  Utility                                                             #
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
