"""
Parameter neighbors of ClaudeBreakout for robustness testing.

A real edge survives small parameter changes; a lucky backtest doesn't.
Run all of them and compare profit factors:

    freqtrade backtesting --userdir ftbot --config ftbot/config.dry.json \
      --strategy-list ClaudeBreakout ClaudeBreakoutFast ClaudeBreakoutSlow \
                      ClaudeBreakoutEma150 ClaudeBreakoutEma250 \
      --timerange 20240601- --breakdown month

Interpretation: if most variants sit near or above PF 1.0, the breakout
edge is structural. If only the exact 20/10/EMA200 combo is positive,
the headline result was noise — do not proceed to paper trading.
"""

from ClaudeBreakout import ClaudeBreakout


class ClaudeBreakoutFast(ClaudeBreakout):
    entry_window = 15
    exit_window = 8


class ClaudeBreakoutSlow(ClaudeBreakout):
    entry_window = 30
    exit_window = 15


class ClaudeBreakoutEma150(ClaudeBreakout):
    trend_ema = 150


class ClaudeBreakoutEma250(ClaudeBreakout):
    trend_ema = 250
    startup_candle_count = 300
