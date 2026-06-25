"""
ClaudeMomoScalp — the redeemed ClaudeConsensus.

== ClaudeConsensus post-mortem: five leaks that killed it ==

1. OVERTRADING (6,919 trades, ~$127 pure fees on $200 wallet)
   Fix: strict regime gate (atr_pct >= 0.008 on 15m) — only enter when a
   single candle move can comfortably clear the 0.12% round-trip fee.
   Also: CooldownPeriod of 4 candles (1h) between same-pair trades, and a
   tighter StoplossGuard.

2. TIGHT STOP → 3,109 INSTANT STOP-OUTS at 1×ATR
   Fix: widen to 2×ATR from entry. A volatile crypto candle routinely
   retraces 0.5–1×ATR before continuing; a 1×ATR stop is noise, not signal.

3. WEAK ADX GATE (25) LET IN SIDEWAYS CHOP
   Fix: require ADX(14) > 30 — only strong directional moves.

4. NO REGIME GATE — TRADED IN LOW-VOL CHOP
   Fix: atr_pct (= ATR/close on 15m) >= 0.008 as a hard entry gate.
   This is the core "fix" — in low-vol regimes the fee hurdle is
   unsurmountable; just sit out.

5. ENTRIES AT EXTENSION, NOT CONTINUATION
   Fix: require MACD histogram > 0 AND rising (positive acceleration)
   for longs; mirror for shorts. This filters "already extended" situations
   where the histogram just crossed zero but is flattening.

== Strategy thesis ==
Momentum continuation on 15m, filtered to high-volatility regimes only.
- Macro trend: 1h EMA20 > EMA50 (long) / EMA20 < EMA50 (short).
- Micro trend:  15m EMA20 vs EMA50, same direction as 1h.
- Strength:     ADX(14) > 30 on 15m.
- Conviction:   vol_ratio > 1.5 (spot volume spike).
- Regime gate:  atr_pct >= 0.008 on 15m (only trade fat-candle environments).
- Entry trigger: MACD histogram > 0 and > prior bar (accelerating momentum).
- Stop:  2×ATR from entry (wide enough to survive noise).
- Target: 1.5×ATR via custom_exit; after reaching 0.75×ATR, trail at 0.75×ATR.
- Cap:   CooldownPeriod 4 candles + StoplossGuard.

Expectation: <<100 trades/month per pair, avg move >=1.5×ATR >> 0.12% fee.
"""

import logging
from datetime import datetime
from typing import Optional

import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, informative, stoploss_from_open
from pandas import DataFrame

logger = logging.getLogger(__name__)


class ClaudeMomoScalp(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = True

    # Hard failsafe only — real stop is ATR-based in custom_stoploss.
    stoploss = -0.20
    use_custom_stoploss = True

    # ROI disabled — exits managed by custom_exit + custom_stoploss.
    minimal_roi = {"0": 100}

    process_only_new_candles = True
    # 50-period EMA on 15m needs ~50 bars; MACD(26) needs 26; ATR 14.
    # 1h informative needs EMA50 on 1h = 50 bars = 50h.  Use 100 to be safe.
    startup_candle_count = 100

    # Position sizing caps (same as ClaudeBreakout / ClaudeConsensus).
    max_stake_usdt = 40.0
    wallet_fraction = 0.20

    # Strategy parameters — kept as class attributes for easy tuning.
    atr_regime_threshold = 0.008   # min ATR/close for regime gate
    adx_min = 30                   # minimum ADX strength
    vol_ratio_min = 1.5            # minimum volume spike multiplier
    atr_stop_mult = 2.0            # stop width in ATR units
    atr_target_mult = 1.5          # profit target in ATR units
    atr_trail_trigger = 0.75       # start trailing after this many ATR profit

    @property
    def protections(self):
        return [
            # 4 × 15m = 1 h cooldown between same-pair trades.
            {"method": "CooldownPeriod", "stop_duration_candles": 4},
            {
                "method": "StoplossGuard",
                # 48 × 15m = 12 h lookback; if 3 stop-outs happen, pause 8h.
                "lookback_period_candles": 48,
                "trade_limit": 3,
                "stop_duration_candles": 32,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                # 192 × 15m = 48 h lookback; max 10% drawdown before 24h pause.
                "lookback_period_candles": 192,
                "trade_limit": 5,
                "stop_duration_candles": 96,
                "max_allowed_drawdown": 0.10,
            },
        ]

    # ── 1h informative: macro trend filter ───────────────────────────────────

    @informative("1h")
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        return dataframe

    # ── 15m indicators ────────────────────────────────────────────────────────

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Trend
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)

        # Strength
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        # Momentum trigger
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd_hist"] = macd["macdhist"]

        # Volatility / regime gate
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]

        # Volume conviction
        dataframe["vol_ratio"] = dataframe["volume"] / dataframe["volume"].rolling(20).mean()

        return dataframe

    # ── Entry ─────────────────────────────────────────────────────────────────

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ── Shared gates (must ALL be true for any entry) ──────────────────
        regime_ok = dataframe["atr_pct"] >= self.atr_regime_threshold
        strength_ok = dataframe["adx"] > self.adx_min
        vol_ok = dataframe["vol_ratio"] > self.vol_ratio_min
        volume_gt0 = dataframe["volume"] > 0

        # ── MACD acceleration (histogram positive AND growing) ─────────────
        macd_bull = (dataframe["macd_hist"] > 0) & (
            dataframe["macd_hist"] > dataframe["macd_hist"].shift(1)
        )
        macd_bear = (dataframe["macd_hist"] < 0) & (
            dataframe["macd_hist"] < dataframe["macd_hist"].shift(1)
        )

        # ── Trend alignment: 15m AND 1h EMA ───────────────────────────────
        trend_bull = (dataframe["ema20"] > dataframe["ema50"]) & (
            dataframe["ema20_1h"] > dataframe["ema50_1h"]
        )
        trend_bear = (dataframe["ema20"] < dataframe["ema50"]) & (
            dataframe["ema20_1h"] < dataframe["ema50_1h"]
        )

        long_mask = (
            regime_ok & strength_ok & vol_ok & macd_bull & trend_bull & volume_gt0
        )
        short_mask = (
            regime_ok & strength_ok & vol_ok & macd_bear & trend_bear & volume_gt0
        )

        dataframe.loc[long_mask, "enter_long"] = 1
        dataframe.loc[long_mask, "enter_tag"] = "momo_long"
        dataframe.loc[short_mask, "enter_short"] = 1
        dataframe.loc[short_mask, "enter_tag"] = "momo_short"
        return dataframe

    # ── Exit signal (trend break) ─────────────────────────────────────────────

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Exit a long if the 15m trend has flipped bearish.
        dataframe.loc[
            (dataframe["ema20"] < dataframe["ema50"])
            & (dataframe["ema20_1h"] < dataframe["ema50_1h"]),
            "exit_long",
        ] = 1
        # Exit a short if the 15m trend has flipped bullish.
        dataframe.loc[
            (dataframe["ema20"] > dataframe["ema50"])
            & (dataframe["ema20_1h"] > dataframe["ema50_1h"]),
            "exit_short",
        ] = 1
        return dataframe

    # ── Position sizing ───────────────────────────────────────────────────────

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

    # ── Custom stoploss: 2×ATR from entry, trail 0.75×ATR after trigger ──────

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
        atr_pct = max(atr_pct, 0.005)  # never let ATR collapse below floor

        trail_trigger = self.atr_trail_trigger * atr_pct

        if current_profit >= trail_trigger:
            # Trail 0.75×ATR behind price once the first target zone is hit.
            # Returning a negative fraction means "distance from CURRENT price".
            return -(self.atr_trail_trigger * atr_pct)

        # Before trigger: fixed 2×ATR stop from entry.
        return stoploss_from_open(
            -(self.atr_stop_mult * atr_pct),
            current_profit,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )

    # ── Custom exit: take profit at 1.5×ATR ──────────────────────────────────

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        atr_pct = self._last_candle_value(pair, "atr_pct") or 0.02
        target = self.atr_target_mult * atr_pct
        if current_profit >= target:
            return "tp_1.5xatr"
        return None

    # ── Helper ────────────────────────────────────────────────────────────────

    def _last_candle_value(self, pair: str, column: str):
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty or column not in dataframe.columns:
            return None
        value = dataframe[column].iloc[-1]
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
