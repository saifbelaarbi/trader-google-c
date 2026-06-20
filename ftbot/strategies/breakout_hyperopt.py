"""
RESEARCH / BACKTEST ONLY — hyperopt-ready ClaudeBreakout.

Exposes the breakout's structural knobs as freqtrade hyperopt parameters so the
"slow-gradient / smarter" direction in ``RESEARCH_returns.md`` (§7, §12 step 6) can
be explored with a **walk-forward** split — optimise on history, validate untouched
on a held-out period. Built on ``ClaudeBreakoutRisk`` so position sizing is
volatility-targeted while the entry/exit/stop windows are tuned.

It only overrides ``populate_indicators`` (to build the Donchian/EMA columns from
the parameter values), ``custom_stoploss`` (ATR multiple) and ``custom_stake_amount``
(risk fraction + stop multiple). The base entry/exit signal logic reads those columns
unchanged, so the search is faithful to the live strategy's mechanics.

Example (walk-forward)::

    freqtrade hyperopt --userdir ftbot --config ftbot/config.dry.json \
      --hyperopt-loss CalmarHyperOptLoss --strategy ClaudeBreakoutHO \
      --timerange 20210101-20241231 --epochs 300 --spaces buy sell stoploss
    # then validate the chosen params, untouched, on 20250101- .

NOT wired into the live paper bot. Adopt a *region*, not the single best epoch
(RESEARCH_returns.md §7), and only after the funding/slippage realism pass.
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import talib.abstract as ta
from freqtrade.strategy import DecimalParameter, IntParameter, stoploss_from_open
from pandas import DataFrame

sys.path.append(str(Path(__file__).parent))

from breakout_research import ClaudeBreakoutRisk  # noqa: E402
from research_sizing import risk_based_stake  # noqa: E402


class ClaudeBreakoutHO(ClaudeBreakoutRisk):
    """Hyperopt-ready variant. Parameter names carry a ``_p`` suffix so they don't
    shadow the base class's plain-int attributes (used by the live-only radar)."""

    # EMA250 needs deep history; cover the widest trend window in the search space.
    startup_candle_count = 320

    entry_window_p = IntParameter(10, 40, default=20, space="buy", optimize=True)
    exit_window_p = IntParameter(5, 20, default=10, space="sell", optimize=True)
    trend_ema_p = IntParameter(100, 300, default=200, space="buy", optimize=True)
    stop_atr_p = DecimalParameter(1.5, 3.5, default=2.0, decimals=1,
                                  space="stoploss", optimize=True)
    risk_fraction_p = DecimalParameter(0.004, 0.012, default=0.0075, decimals=4,
                                       space="buy", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=int(self.trend_ema_p.value))
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        entry_w = int(self.entry_window_p.value)
        exit_w = int(self.exit_window_p.value)
        dataframe["dc_entry_high"] = dataframe["high"].rolling(entry_w).max().shift(1)
        dataframe["dc_entry_low"] = dataframe["low"].rolling(entry_w).min().shift(1)
        dataframe["dc_exit_high"] = dataframe["high"].rolling(exit_w).max().shift(1)
        dataframe["dc_exit_low"] = dataframe["low"].rolling(exit_w).min().shift(1)
        return dataframe

    def custom_stoploss(
        self,
        pair: str,
        trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> Optional[float]:
        atr_pct = self._last_candle_value(pair, "atr_pct") or 0.02
        atr_pct = max(atr_pct, 0.005)
        return stoploss_from_open(
            -float(self.stop_atr_p.value) * atr_pct,
            current_profit,
            is_short=trade.is_short,
            leverage=trade.leverage,
        )

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
        equity = self.wallets.get_total_stake_amount() if self.wallets else 200.0
        atr_pct = self._last_candle_value(pair, "atr_pct") or 0.02
        return risk_based_stake(
            equity,
            atr_pct,
            risk_fraction=float(self.risk_fraction_p.value),
            stop_atr_mult=float(self.stop_atr_p.value),
            notional_cap_fraction=self.wallet_fraction,
            min_stake=min_stake,
            max_stake=max_stake,
        )
