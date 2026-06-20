"""
RESEARCH / BACKTEST ONLY — variants of ClaudeBreakout that implement the
returns-optimization levers documented in ``ftbot/RESEARCH_returns.md``.

NONE of these are wired into the live paper bot — ``config.dry.json`` still runs
plain ``ClaudeBreakout``. Run them only in backtesting / hyperopt to measure each
lever before any go-live decision (RESEARCH_returns.md §12), e.g.::

    freqtrade backtesting --userdir ftbot --config ftbot/config.dry.json \
      --strategy-list ClaudeBreakout ClaudeBreakoutRisk ClaudeBreakoutCorr \
                      ClaudeBreakoutPyramid ClaudeBreakoutChandelier ClaudeBreakoutPro \
      --timerange 20240601- --breakdown month

Composition is done with small mixins so each lever can be read and tested in
isolation; the concrete strategy classes at the bottom combine them. Only classes
that subclass ``ClaudeBreakout`` (an ``IStrategy``) are picked up by freqtrade — the
mixins are plain objects and are ignored by strategy discovery.

The pure math lives in ``research_sizing.py`` (dependency-free, unit-tested in CI);
these classes only adapt it to the freqtrade callback signatures.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from freqtrade.exchange import timeframe_to_prev_date
from freqtrade.persistence import Trade
from pandas import DataFrame

# freqtrade puts the strategies dir on sys.path at load time; add it explicitly so
# the sibling-module imports also resolve under plain backtests and tooling.
sys.path.append(str(Path(__file__).parent))

from ClaudeBreakout import ClaudeBreakout  # noqa: E402
from research_sizing import (  # noqa: E402
    chandelier_stop,
    crowding_factor,
    pyramid_should_add,
    risk_based_stake,
)

logger = logging.getLogger(__name__)


class RiskSizingMixin:
    """Lever #1 — volatility-targeted ("unit") sizing: equal $ risk per trade."""

    risk_fraction = 0.0075  # ~0.75% of equity risked at the 2×ATR stop

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
            risk_fraction=self.risk_fraction,
            stop_atr_mult=2.0,
            notional_cap_fraction=self.wallet_fraction,
            min_stake=min_stake,
            max_stake=max_stake,
        )


class CrowdingMixin:
    """Lever #4 — down-scale a new entry as same-direction positions pile up.

    Must sit *before* a sizing mixin in the MRO so ``super()`` returns the
    risk-based stake, which this then multiplies by the crowding factor.
    """

    crowding_k = 0.5

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
        stake = super().custom_stake_amount(
            pair, current_time, current_rate, proposed_stake, min_stake,
            max_stake, leverage, entry_tag, side, **kwargs,
        )
        is_short = side == "short"
        try:
            open_same = sum(
                1 for t in Trade.get_open_trades() if t.is_short == is_short
            )
        except Exception:
            open_same = 0
        stake *= crowding_factor(open_same, k=self.crowding_k)
        if min_stake:
            stake = max(stake, min_stake)
        return min(stake, max_stake)


class PyramidMixin:
    """Lever #2 — add units in favour (Turtle pyramiding), capped at ``max_units``."""

    position_adjustment_enable = True
    max_units = 4
    max_entry_position_adjustment = 3  # max_units - 1
    step_atr = 0.5

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: Optional[float],
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ) -> Optional[float]:
        adds_done = trade.nr_of_successful_entries - 1
        atr_pct = self._last_candle_value(trade.pair, "atr_pct") or 0.02
        if not pyramid_should_add(
            trade.open_rate,
            current_rate,
            is_short=trade.is_short,
            atr_pct=atr_pct,
            adds_done=adds_done,
            max_units=self.max_units,
            step_atr=self.step_atr,
        ):
            return None
        equity = self.wallets.get_total_stake_amount() if self.wallets else 200.0
        return risk_based_stake(
            equity,
            atr_pct,
            risk_fraction=getattr(self, "risk_fraction", 0.0075),
            stop_atr_mult=2.0,
            notional_cap_fraction=self.wallet_fraction,
            min_stake=min_stake,
            max_stake=max_stake,
        )


class ChandelierMixin:
    """Lever #6 — chandelier trailing exit instead of the fixed Donchian-10 exit."""

    chandelier_n = 3.0

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Disable the signal-based Donchian exit; the trail is handled in custom_exit.
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
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None
        entry_candle = timeframe_to_prev_date(self.timeframe, trade.open_date_utc)
        recent = dataframe[dataframe["date"] >= entry_candle]
        if recent.empty:
            return None
        atr = float(recent.iloc[-1]["atr"])
        if trade.is_short:
            extreme = float(recent["low"].min())
            stop = chandelier_stop(extreme, atr, is_short=True, n_atr=self.chandelier_n)
            if current_rate >= stop:
                return "chandelier_short"
        else:
            extreme = float(recent["high"].max())
            stop = chandelier_stop(extreme, atr, is_short=False, n_atr=self.chandelier_n)
            if current_rate <= stop:
                return "chandelier_long"
        return None


# --- Concrete backtest variants --------------------------------------------------

class ClaudeBreakoutRisk(RiskSizingMixin, ClaudeBreakout):
    """A — risk-based unit sizing only."""


class ClaudeBreakoutCorr(CrowdingMixin, RiskSizingMixin, ClaudeBreakout):
    """B — risk sizing + correlation/crowding down-scaling."""


class ClaudeBreakoutPyramid(PyramidMixin, RiskSizingMixin, ClaudeBreakout):
    """C — risk sizing + Turtle pyramiding."""


class ClaudeBreakoutChandelier(ChandelierMixin, RiskSizingMixin, ClaudeBreakout):
    """D — risk sizing + chandelier trailing exit."""


class ClaudeBreakoutPro(
    ChandelierMixin, PyramidMixin, CrowdingMixin, RiskSizingMixin, ClaudeBreakout
):
    """E — all levers combined: sizing + crowding + pyramiding + chandelier exit."""
