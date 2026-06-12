"""
ClaudeBreakout — V4: strategy family change from mean-reversion-to-trend
(pullback entries) to classic breakout trend-following.

Why the family change: V1→V3 progressively fixed fees, stops and timing
(PF 0.40 → 0.51 → 0.75) but every variant bought weakness inside a trend
and capped winners with tight trails. V3's autopsy: winners locked ~1×ATR
while stop-outs took -2×ATR; shorts lost money even in a -40% market;
"pullbacks" that kept falling produced full-size stop-outs within 2h.
The premise — not the parameters — failed. Agreed rule: change family.

V4 (turtle-style, 4h candles):
  Entry : close breaks the prior 20-bar high (long) / low (short),
          filtered by EMA200 side — only trade with the macro trend.
  Exit  : close crosses the opposite 10-bar extreme (Donchian exit),
          letting winners run for multi-day trends.
  Stop  : 2×ATR(4h) from entry. No profit target, no trail — the
          Donchian exit is the trail.

Expectation profile: win rate ~35-45%, most trades small losses, a few
multi-ATR winners carry the book. Judge on profit factor + expectancy,
not win rate.
"""

from datetime import datetime
from typing import Optional

import talib.abstract as ta
from freqtrade.exchange import timeframe_to_prev_date
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_open
from pandas import DataFrame


class ClaudeBreakout(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "4h"
    can_short = True

    # Hard failsafe only — the real stop is ATR-based in custom_stoploss.
    stoploss = -0.20
    use_custom_stoploss = True

    minimal_roi = {"0": 100}

    process_only_new_candles = True
    startup_candle_count = 250  # EMA200 on 4h needs deep history

    entry_window = 20  # ~3.3 days of 4h candles
    exit_window = 10
    trend_ema = 200

    max_stake_usdt = 40.0
    wallet_fraction = 0.20

    # Telegram "breakout radar": once per candle, per-pair bias + distance
    # to the Donchian trigger. Live/dry-run only; set False to silence.
    radar_enabled = True

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        if not self.radar_enabled or self.dp.runmode.value not in ("live", "dry_run"):
            return
        candle = timeframe_to_prev_date(self.timeframe, current_time)
        if getattr(self, "_last_radar_candle", None) == candle:
            return
        lines = []
        for pair in self.dp.current_whitelist():
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or dataframe.empty:
                continue
            last = dataframe.iloc[-1]
            cols = ["close", "ema200", "dc_entry_high", "dc_entry_low"]
            if last[cols].isna().any():
                continue
            coin = pair.split("/")[0]
            if last["close"] > last["ema200"]:
                dist = (last["dc_entry_high"] / last["close"] - 1) * 100
                text = f"{coin}: ⬆ long bias — {dist:+.1f}% to {self.entry_window}-bar high"
            else:
                dist = (1 - last["dc_entry_low"] / last["close"]) * 100
                text = f"{coin}: ⬇ short bias — {dist:+.1f}% to {self.entry_window}-bar low"
            lines.append((dist, text))
        if not lines:
            return  # dataframes not analyzed yet — retry next loop
        self._last_radar_candle = candle
        lines.sort(key=lambda item: item[0])
        slots = Trade.get_open_trade_count()
        self.dp.send_msg(
            f"📡 Breakout radar — {candle:%d %b %H:%M} UTC "
            f"(slots {slots}/{self.config.get('max_open_trades', '?')})\n"
            + "\n".join(text for _, text in lines)
        )

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 1},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 84,  # 2 weeks of 4h candles
                "trade_limit": 4,
                "stop_duration_candles": 12,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 180,  # 30 days
                "trade_limit": 6,
                "stop_duration_candles": 42,
                "max_allowed_drawdown": 0.15,
            },
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=self.trend_ema)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        # Donchian channels, shifted so the current candle can break them.
        dataframe["dc_entry_high"] = dataframe["high"].rolling(self.entry_window).max().shift(1)
        dataframe["dc_entry_low"] = dataframe["low"].rolling(self.entry_window).min().shift(1)
        dataframe["dc_exit_high"] = dataframe["high"].rolling(self.exit_window).max().shift(1)
        dataframe["dc_exit_low"] = dataframe["low"].rolling(self.exit_window).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        long_mask = (
            (dataframe["close"] > dataframe["dc_entry_high"])
            & (dataframe["close"] > dataframe["ema200"])
            & (dataframe["volume"] > 0)
        )
        short_mask = (
            (dataframe["close"] < dataframe["dc_entry_low"])
            & (dataframe["close"] < dataframe["ema200"])
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[long_mask, "enter_long"] = 1
        dataframe.loc[long_mask, "enter_tag"] = "breakout_long"
        dataframe.loc[short_mask, "enter_short"] = 1
        dataframe.loc[short_mask, "enter_tag"] = "breakout_short"
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Turtle exit: opposite 10-bar extreme — gives winners room to run.
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
