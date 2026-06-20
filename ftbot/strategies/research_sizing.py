"""
Pure, dependency-free helpers for the ClaudeBreakout research variants.

These functions hold the *math* for the returns-optimization levers described in
``ftbot/RESEARCH_returns.md`` — risk-based ("unit") sizing, pyramiding,
correlation/crowding control, and the chandelier exit. They deliberately import
nothing from freqtrade, talib, or pandas so they can be unit-tested in CI without
the trading stack (or the TA-Lib C library) installed.

The freqtrade strategy classes in ``breakout_research.py`` call these helpers from
their override methods.

RESEARCH / BACKTEST ONLY — none of this is wired into the live ClaudeBreakout paper
bot. See the go-live rules in CLAUDE.md and OVERHAUL_PLAN.md before promoting any
variant.
"""

from __future__ import annotations


def risk_based_stake(
    equity: float,
    atr_pct: float,
    *,
    risk_fraction: float = 0.0075,
    stop_atr_mult: float = 2.0,
    notional_cap_fraction: float = 0.20,
    min_stake: float | None = None,
    max_stake: float | None = None,
    atr_pct_floor: float = 0.005,
) -> float:
    """Volatility-targeted ("unit") stake — Turtle lever #1.

    Size the position so it loses approximately ``risk_fraction`` of ``equity`` if
    the ``stop_atr_mult``×ATR stop is hit. Because the stop distance is in ATR
    terms, inverting it makes volatile pairs receive a *smaller* notional and quiet
    pairs a *larger* notional, equalising dollar risk per trade (the classic Turtle
    unit). A notional ceiling (``notional_cap_fraction`` of equity) keeps any single
    unit from dominating the book.

    Returns the stake in quote currency, clamped to ``[min_stake, max_stake]`` when
    those are provided.
    """
    atr_pct = max(float(atr_pct), atr_pct_floor)
    stop_distance = stop_atr_mult * atr_pct
    risk_dollars = max(float(equity), 0.0) * risk_fraction
    stake = risk_dollars / stop_distance if stop_distance > 0 else 0.0
    stake = min(stake, max(float(equity), 0.0) * notional_cap_fraction)
    if min_stake is not None:
        stake = max(stake, min_stake)
    if max_stake is not None:
        stake = min(stake, max_stake)
    return stake


def pyramid_should_add(
    entry_rate: float,
    current_rate: float,
    *,
    is_short: bool,
    atr_pct: float,
    adds_done: int,
    max_units: int = 4,
    step_atr: float = 0.5,
    atr_pct_floor: float = 0.005,
) -> bool:
    """Decide whether to add the next pyramid unit — Turtle lever #2.

    Add a unit each time price has advanced a further ``step_atr``×ATR in the
    trade's favour, up to ``max_units`` total entries. ``adds_done`` counts adds
    already made (the initial entry is unit 1, i.e. ``adds_done == 0`` after it), so
    the thresholds are 0.5×, 1.0×, 1.5×… ATR measured from the original entry — a
    monotonic proxy for "0.5×ATR since the last fill" that needs no fill history.

    Losers never reach a positive threshold, so only winners are scaled.
    """
    if adds_done >= max_units - 1:
        return False
    atr_pct = max(float(atr_pct), atr_pct_floor)
    favourable_move = current_rate / entry_rate - 1.0
    if is_short:
        favourable_move = -favourable_move
    threshold = (adds_done + 1) * step_atr * atr_pct
    return favourable_move >= threshold


def crowding_factor(open_same_direction: int, *, k: float = 0.5) -> float:
    """Down-scale a new entry as same-direction positions pile up — lever #4.

    ``open_same_direction`` is the number of already-open trades on the SAME side
    (long or short), excluding the new one. Returns ``1 / (1 + k·n)`` → 1.0, 0.67,
    0.5, 0.4… for ``k = 0.5``. Counters the hidden correlation in an all-BTC-beta
    book where N simultaneous same-side trades behave like one N× leveraged bet
    (see RESEARCH_returns.md §4).
    """
    n = max(int(open_same_direction), 0)
    return 1.0 / (1.0 + k * n)


def chandelier_stop(
    extreme_since_entry: float,
    atr: float,
    *,
    is_short: bool,
    n_atr: float = 3.0,
) -> float:
    """Chandelier trailing-stop price — lever #6.

    Long: ``highest_high_since_entry − n_atr·ATR``.
    Short: ``lowest_low_since_entry + n_atr·ATR``.

    The stop ratchets with the trade's best excursion, letting strong trends run
    while exiting faster than a fixed Donchian channel once momentum stalls.
    """
    if is_short:
        return extreme_since_entry + n_atr * atr
    return extreme_since_entry - n_atr * atr
