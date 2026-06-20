"""Unit tests for the ClaudeBreakout research-sizing helpers.

Pure-math coverage of the returns-optimization levers (RESEARCH_returns.md). No
freqtrade / TA-Lib dependency — see tests/conftest.py for the import path setup.
"""

import pytest
from research_sizing import (
    chandelier_stop,
    crowding_factor,
    pyramid_should_add,
    risk_based_stake,
)

# --- risk_based_stake (lever #1) -------------------------------------------------

def test_quiet_pair_gets_larger_notional_than_volatile_pair():
    # Same equity + risk budget: lower ATR => larger stake (equal $ risk at stop).
    quiet = risk_based_stake(1000, 0.01, risk_fraction=0.01, notional_cap_fraction=1.0)
    volatile = risk_based_stake(1000, 0.04, risk_fraction=0.01, notional_cap_fraction=1.0)
    assert quiet > volatile


def test_dollar_risk_at_stop_is_constant_across_pairs():
    # stake * (2*atr_pct) == risk_dollars, independent of atr_pct.
    for atr_pct in (0.01, 0.02, 0.05):
        stake = risk_based_stake(1000, atr_pct, risk_fraction=0.01,
                                 notional_cap_fraction=1.0)
        assert stake * (2 * atr_pct) == pytest.approx(10.0)  # 1% of 1000


def test_notional_cap_limits_stake():
    # Tiny ATR would imply a huge notional; the cap holds it down.
    stake = risk_based_stake(1000, 0.001, risk_fraction=0.01, notional_cap_fraction=0.2)
    assert stake == pytest.approx(200.0)  # 20% of equity


def test_atr_floor_prevents_blowup_on_zero_volatility():
    stake = risk_based_stake(1000, 0.0, risk_fraction=0.01, notional_cap_fraction=1.0,
                             atr_pct_floor=0.005)
    # floored atr_pct=0.005 -> stop_distance 0.01 -> stake 10/0.01 = 1000
    assert stake == pytest.approx(1000.0)


def test_min_and_max_stake_clamp():
    assert risk_based_stake(1000, 0.02, risk_fraction=0.0001, min_stake=5.0) >= 5.0
    assert risk_based_stake(1000, 0.001, risk_fraction=0.5, max_stake=50.0,
                            notional_cap_fraction=1.0) == pytest.approx(50.0)


# --- pyramid_should_add (lever #2) -----------------------------------------------

def test_no_add_below_threshold():
    assert not pyramid_should_add(100, 100.1, is_short=False, atr_pct=0.02,
                                  adds_done=0, step_atr=0.5)


def test_add_when_move_reaches_half_atr():
    # +1% move == 0.5 * 0.02 threshold exactly.
    assert pyramid_should_add(100, 101.0, is_short=False, atr_pct=0.02,
                              adds_done=0, step_atr=0.5)


def test_threshold_grows_with_each_unit():
    # After one add, need >=1.0*ATR (2%); +1% no longer enough.
    assert not pyramid_should_add(100, 101.0, is_short=False, atr_pct=0.02,
                                  adds_done=1, step_atr=0.5)
    assert pyramid_should_add(100, 102.0, is_short=False, atr_pct=0.02,
                              adds_done=1, step_atr=0.5)


def test_no_add_at_max_units():
    assert not pyramid_should_add(100, 200.0, is_short=False, atr_pct=0.02,
                                  adds_done=3, max_units=4)


def test_short_side_adds_on_downmove():
    assert pyramid_should_add(100, 99.0, is_short=True, atr_pct=0.02,
                              adds_done=0, step_atr=0.5)
    assert not pyramid_should_add(100, 101.0, is_short=True, atr_pct=0.02,
                                  adds_done=0, step_atr=0.5)


# --- crowding_factor (lever #4) --------------------------------------------------

def test_crowding_factor_decreases_with_crowding():
    assert crowding_factor(0) == pytest.approx(1.0)
    assert crowding_factor(1, k=0.5) == pytest.approx(1 / 1.5)
    assert crowding_factor(2, k=0.5) == pytest.approx(0.5)
    assert crowding_factor(3, k=0.5) > 0


def test_crowding_factor_negative_input_is_clamped():
    assert crowding_factor(-5) == pytest.approx(1.0)


# --- chandelier_stop (lever #6) --------------------------------------------------

def test_chandelier_long_below_extreme():
    stop = chandelier_stop(110, 2.0, is_short=False, n_atr=3.0)
    assert stop == pytest.approx(104.0)


def test_chandelier_short_above_extreme():
    stop = chandelier_stop(90, 2.0, is_short=True, n_atr=3.0)
    assert stop == pytest.approx(96.0)
