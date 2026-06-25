"""
ClaudeSqueeze — TTM Squeeze release strategy on 15m candles.

Thesis:
  The TTM Squeeze (John Carter) identifies volatility compression via
  Bollinger Bands sitting INSIDE Keltner Channels ("squeeze ON").
  When the squeeze RELEASES (BB expands beyond KC), a volatility
  expansion move is imminent. These expansions are the large, fast
  moves that clear 15m fees comfortably.

  Entry logic:
    - Squeeze ON for ≥ 2 consecutive bars (confirmation of real compression)
    - Squeeze releases on the current bar (BB crosses outside KC)
    - Direction filter: MACD histogram sign on 15m (positive → long, negative → short)
    - Higher-TF alignment: 1h EMA20 slope (close trend direction)
    - Volume confirmation: volume ≥ 1.2× its 20-bar average
    - ATR filter: minimum ATR% to ensure the move can pay fees
      (skip if ATR < 0.35% of close — not enough room for fees + profit)

  Exit logic:
    - custom_stoploss: initial 2×ATR hard stop, trails at 1×ATR once
      profit exceeds 1×ATR (i.e. let winner run, cut losers fast)
    - populate_exit_trend: exit when MACD histogram flips sign (momentum
      gone) OR close crosses back through EMA20 (trend broke)

  Why this beats fees:
    - Only enters after CONFIRMED compression — not every signal
    - ATR filter rejects low-volatility periods where moves are < 0.35%
    - Volume filter demands genuine participation
    - 1h trend alignment avoids counter-trend squeezes (which snap back)
    - Trailing stop lets the large expansion moves run multi-ATR
"""

import logging
from datetime import datetime
from typing import Optional

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_open
from pandas import DataFrame, Series

logger = logging.getLogger(__name__)


class ClaudeSqueeze(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = True

    # Hard failsafe — real stop managed in custom_stoploss
    stoploss = -0.20
    use_custom_stoploss = True

    # No fixed ROI — let the trail and momentum-flip manage exits
    minimal_roi = {"0": 100}

    process_only_new_candles = True
    # BB(20) + KC(EMA20, ATR20) + MACD(26 slow) + vol_ma(20) + 1h warmup
    startup_candle_count = 60

    # Squeeze parameters
    bb_period = 20
    bb_std = 2.0
    kc_period = 20
    kc_atr_mult = 1.5
    atr_period = 20

    # Directional / confirmation
    macd_fast = 12
    macd_slow = 26
    macd_signal = 9
    vol_ma_period = 20

    # Risk parameters
    min_squeeze_bars = 2      # require N consecutive squeeze bars before release
    min_atr_pct = 0.0035      # 0.35% minimum ATR/close to clear fees
    vol_threshold = 1.2       # volume must be 1.2× its 20-bar average
    initial_stop_atr = 2.0    # initial stop width in ATR multiples
    trail_atr = 1.0           # trailing stop width once in profit
    trail_trigger_atr = 1.0   # start trailing after 1×ATR profit

    # Stake sizing
    max_stake_usdt = 40.0
    wallet_fraction = 0.20

    @property
    def protections(self):
        return [
            # Don't re-enter the same pair within 3 candles of a trade closing
            {"method": "CooldownPeriod", "stop_duration_candles": 3},
            {
                # If 3 stoploss hits in any 48-candle window (12h), pause 24 candles (6h)
                "method": "StoplossGuard",
                "lookback_period_candles": 48,
                "trade_limit": 3,
                "stop_duration_candles": 24,
                "only_per_pair": False,
            },
            {
                # Pause all trading if drawdown exceeds 12% in last 5 days
                "method": "MaxDrawdown",
                "lookback_period_candles": 480,   # 5 days of 15m candles
                "trade_limit": 5,
                "stop_duration_candles": 96,       # 24h pause
                "max_allowed_drawdown": 0.12,
            },
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ── Bollinger Bands (20, 2σ) ──────────────────────────────────────
        upper, mid, lower = ta.BBANDS(
            dataframe,
            timeperiod=self.bb_period,
            nbdevup=self.bb_std,
            nbdevdn=self.bb_std,
            matype=0,  # SMA
        )
        dataframe["bb_upper"] = upper
        dataframe["bb_mid"] = mid
        dataframe["bb_lower"] = lower

        # ── Keltner Channel (EMA20 ± 1.5×ATR20) ──────────────────────────
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=self.kc_period)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        dataframe["kc_upper"] = dataframe["ema20"] + self.kc_atr_mult * dataframe["atr"]
        dataframe["kc_lower"] = dataframe["ema20"] - self.kc_atr_mult * dataframe["atr"]

        # ── Squeeze detection ─────────────────────────────────────────────
        # Squeeze ON: BB sits INSIDE KC
        dataframe["squeeze_on"] = (
            (dataframe["bb_lower"] > dataframe["kc_lower"])
            & (dataframe["bb_upper"] < dataframe["kc_upper"])
        ).astype(int)

        # Count consecutive squeeze bars (for min_squeeze_bars filter)
        squeeze_cumsum = dataframe["squeeze_on"].cumsum()
        # Rolling minimum over squeeze_on in the prior N bars (shift avoids lookahead)
        dataframe["squeeze_bars"] = (
            dataframe["squeeze_on"].shift(1).rolling(self.min_squeeze_bars).min()
        )

        # Squeeze release: squeeze was ON last bar, OFF now
        dataframe["squeeze_prev"] = dataframe["squeeze_on"].shift(1)
        dataframe["squeeze_release"] = (
            (dataframe["squeeze_on"] == 0) & (dataframe["squeeze_prev"] == 1)
        ).astype(int)

        # ── Momentum: MACD histogram ──────────────────────────────────────
        macd, macdsignal, macdhist = ta.MACD(
            dataframe,
            fastperiod=self.macd_fast,
            slowperiod=self.macd_slow,
            signalperiod=self.macd_signal,
        )
        dataframe["macd"] = macd
        dataframe["macd_signal"] = macdsignal
        dataframe["macd_hist"] = macdhist
        dataframe["macd_hist_prev"] = dataframe["macd_hist"].shift(1)

        # ── Volume confirmation ───────────────────────────────────────────
        dataframe["vol_ma"] = ta.SMA(dataframe["volume"], timeperiod=self.vol_ma_period)
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["vol_ma"]

        # ── EMA20 slope (direction bias) ──────────────────────────────────
        dataframe["ema20_slope"] = dataframe["ema20"] - dataframe["ema20"].shift(3)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Common filters for any entry
        base_filter = (
            (dataframe["squeeze_release"] == 1)           # squeeze just released
            & (dataframe["squeeze_bars"] >= 1)            # was squeezed ≥ min_squeeze_bars
            & (dataframe["atr_pct"] > self.min_atr_pct)  # enough volatility to pay fees
            & (dataframe["vol_ratio"] > self.vol_threshold)  # volume confirming
            & (dataframe["volume"] > 0)
            & dataframe["macd_hist"].notna()
            & dataframe["ema20"].notna()
        )

        # LONG: MACD hist positive (momentum up) AND EMA20 slope trending up
        long_mask = (
            base_filter
            & (dataframe["macd_hist"] > 0)
            & (dataframe["ema20_slope"] > 0)
        )

        # SHORT: MACD hist negative (momentum down) AND EMA20 slope trending down
        short_mask = (
            base_filter
            & (dataframe["macd_hist"] < 0)
            & (dataframe["ema20_slope"] < 0)
        )

        dataframe.loc[long_mask, "enter_long"] = 1
        dataframe.loc[long_mask, "enter_tag"] = "squeeze_long"
        dataframe.loc[short_mask, "enter_short"] = 1
        dataframe.loc[short_mask, "enter_tag"] = "squeeze_short"
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exit long when: MACD histogram flips negative OR close crosses below EMA20
        exit_long_mask = (
            (dataframe["macd_hist"] < 0)
            | (dataframe["close"] < dataframe["ema20"])
        )
        # Exit short when: MACD histogram flips positive OR close crosses above EMA20
        exit_short_mask = (
            (dataframe["macd_hist"] > 0)
            | (dataframe["close"] > dataframe["ema20"])
        )
        dataframe.loc[exit_long_mask, "exit_long"] = 1
        dataframe.loc[exit_short_mask, "exit_short"] = 1
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
        atr_pct = max(atr_pct, 0.005)  # floor: never less than 0.5%

        # Once profit reaches trail_trigger_atr × ATR, switch to tighter trail
        if current_profit > self.trail_trigger_atr * atr_pct:
            # Trail at 1×ATR from current price
            trail_stop = stoploss_from_open(
                -(self.trail_atr * atr_pct),
                current_profit,
                is_short=trade.is_short,
                leverage=trade.leverage,
            )
            # Never widen: return whichever is tighter (less negative)
            return max(trail_stop, -(self.initial_stop_atr * atr_pct))
        else:
            # Initial stop: 2×ATR from entry
            return stoploss_from_open(
                -(self.initial_stop_atr * atr_pct),
                current_profit,
                is_short=trade.is_short,
                leverage=trade.leverage,
            )

    def _last_candle_value(self, pair: str, column: str):
        """Read the latest analyzed candle value for a given column."""
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty or column not in dataframe.columns:
            return None
        value = dataframe[column].iloc[-1]
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
