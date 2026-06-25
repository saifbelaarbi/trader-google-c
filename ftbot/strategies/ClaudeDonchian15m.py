"""
ClaudeDonchian15m — Turtle-style Donchian breakout compressed to 15m candles.

This is a deliberate timeframe-compression experiment: ClaudeBreakout (V4)
ran 4h Donchian channels and produced PF 1.14 / +38.7% — the only strategy
in this repo with a positive profit factor. This file ports the identical
philosophy to 15m bars to test whether the breakout edge survives on a
shorter timeframe, or whether it depends on the 4h resolution.

Design decisions vs. the 4h original:
  entry_window = 48  (≈12h of 15m bars, mirrors 3-day Donchian of 4h)
  exit_window  = 24  (≈6h, mirrors the 4h 10-bar Donchian exit)
  EMA200 filter stays on the 1h timeframe (macro trend anchor unchanged)
  ATR stop stays at 2×ATR(14) on the base timeframe (15m ATR tighter → faster stop)
  Volatility floor: atr_pct ≥ 0.004 to skip dead chop and avoid fee drag
    (0.004 * 2 = 0.8% per leg >> 0.12% round-trip fee; gives 6× fee coverage)

Expectation profile: same as the 4h parent — low win-rate, fat right tail.
Profit factor and expectancy are the primary success metrics.

If PF < 1.0 after honest testing, the conclusion is that the breakout edge
requires the 4h timeframe; the experiment is still valid data.
"""

import logging
from datetime import datetime
from typing import Optional

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, informative, stoploss_from_open
from pandas import DataFrame

logger = logging.getLogger(__name__)


class ClaudeDonchian15m(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = True

    # Hard failsafe only — the real stop is ATR-based in custom_stoploss.
    stoploss = -0.20
    use_custom_stoploss = True

    minimal_roi = {"0": 100}

    process_only_new_candles = True
    # 1h EMA200 needs 200 1h bars. Each 1h = 4 15m candles. Freqtrade pads
    # informative frames separately, but we also need ~48 bars for Donchian
    # on the 15m frame itself. 300 is safe.
    startup_candle_count = 300

    # Donchian windows (15m candles)
    entry_window = 48   # ≈12h (matches ~3-day window of the 4h parent)
    exit_window = 24    # ≈6h
    trend_ema = 200     # applied on the 1h informative

    # Volatility floor — skip entry when market is choppy/dead
    min_atr_pct = 0.004  # 0.4% ATR gives ≥6× fee coverage on a 2×ATR stop

    max_stake_usdt = 40.0
    wallet_fraction = 0.20

    @informative("1h")
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=self.trend_ema)
        return dataframe

    @property
    def protections(self):
        return [
            # 1-candle cooldown between entries (same pair)
            {"method": "CooldownPeriod", "stop_duration_candles": 2},
            {
                # 2-week lookback in 15m units = 14 * 24 * 4 = 1344
                "method": "StoplossGuard",
                "lookback_period_candles": 1344,
                "trade_limit": 4,
                "stop_duration_candles": 48,   # 12h pause after stop cluster
                "only_per_pair": False,
            },
            {
                # 30-day lookback in 15m = 30 * 24 * 4 = 2880
                "method": "MaxDrawdown",
                "lookback_period_candles": 2880,
                "trade_limit": 6,
                "stop_duration_candles": 168,  # 42h pause
                "max_allowed_drawdown": 0.15,
            },
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]

        # Donchian channels — shifted by 1 so the current bar can break the
        # PRIOR window's extreme (no lookahead), matching ClaudeBreakout.
        dataframe["dc_entry_high"] = (
            dataframe["high"].rolling(self.entry_window).max().shift(1)
        )
        dataframe["dc_entry_low"] = (
            dataframe["low"].rolling(self.entry_window).min().shift(1)
        )
        dataframe["dc_exit_high"] = (
            dataframe["high"].rolling(self.exit_window).max().shift(1)
        )
        dataframe["dc_exit_low"] = (
            dataframe["low"].rolling(self.exit_window).min().shift(1)
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Volatility floor: skip entries in dead/choppy market.
        vol_ok = dataframe["atr_pct"] >= self.min_atr_pct

        # Macro filter: trade WITH the 1h EMA200 trend only.
        above_trend = dataframe["close"] > dataframe["ema200_1h"]
        below_trend = dataframe["close"] < dataframe["ema200_1h"]

        long_mask = (
            (dataframe["close"] > dataframe["dc_entry_high"])
            & above_trend
            & vol_ok
            & (dataframe["volume"] > 0)
        )
        short_mask = (
            (dataframe["close"] < dataframe["dc_entry_low"])
            & below_trend
            & vol_ok
            & (dataframe["volume"] > 0)
        )

        dataframe.loc[long_mask, "enter_long"] = 1
        dataframe.loc[long_mask, "enter_tag"] = "donchian_long_15m"
        dataframe.loc[short_mask, "enter_short"] = 1
        dataframe.loc[short_mask, "enter_tag"] = "donchian_short_15m"

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Turtle exit: close crosses the opposite short-window extreme.
        # Gives winners room to run while cutting losers quickly.
        dataframe.loc[
            dataframe["close"] < dataframe["dc_exit_low"], "exit_long"
        ] = 1
        dataframe.loc[
            dataframe["close"] > dataframe["dc_exit_high"], "exit_short"
        ] = 1
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
        # Fixed 2×ATR disaster stop from entry; the Donchian exit manages
        # winners (identical philosophy to ClaudeBreakout on 4h).
        return stoploss_from_open(
            -2 * atr_pct,
            current_profit,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )

    def _last_candle_value(self, pair: str, column: str):
        """Return the last analyzed candle's scalar value for a column, or None."""
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty or column not in dataframe.columns:
            return None
        value = dataframe[column].iloc[-1]
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
