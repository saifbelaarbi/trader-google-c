# ftbot strategies — index

## Live (do not edit during the paper-trading window)

| File | Class | Status |
|---|---|---|
| `ClaudeBreakout.py` | `ClaudeBreakout` | **ACTIVE** — the dry-run paper bot. Donchian 20/10 + EMA200, 4h. |
| `breakout_variants.py` | `ClaudeBreakout{Fast,Slow,Ema150,Ema250}` | robustness neighbours (backtest only). |
| `ClaudeConsensus.py`, `ClaudePullback.py`, `ClaudeTrend1h.py` | — | retired V1–V3 (backtest-negative; kept as record). |

`config.dry.json` runs **`ClaudeBreakout`**. Changing its parameters/logic mid-window
invalidates the experiment — see `CLAUDE.md`.

## Research / backtest-only (returns-optimization workstream)

Rationale and lever-by-lever analysis: **`../RESEARCH_returns.md`**.

| File | Classes | Lever(s) |
|---|---|---|
| `research_sizing.py` | _(pure helpers, no freqtrade/TA-Lib)_ | the math: `risk_based_stake`, `pyramid_should_add`, `crowding_factor`, `chandelier_stop` |
| `breakout_research.py` | `ClaudeBreakoutRisk` | volatility-targeted unit sizing (#1) |
| | `ClaudeBreakoutCorr` | + correlation/crowding (#4) |
| | `ClaudeBreakoutPyramid` | + Turtle pyramiding (#2) |
| | `ClaudeBreakoutChandelier` | + chandelier exit (#6) |
| | `ClaudeBreakoutPro` | all levers combined |
| `breakout_hyperopt.py` | `ClaudeBreakoutHO` | hyperopt-ready (walk-forward, #7) |

The helper math is unit-tested in `tests/test_research_sizing.py` and gated by the
`ftbot CI` workflow; the strategy files are byte-compiled there (TA-Lib/freqtrade are
not installed in CI).

## Running the research (on the PC — cloud sessions can't reach the exchange)

```powershell
# A/B the levers against the live baseline (do the funding/slippage realism pass first)
freqtrade backtesting --userdir ftbot --config ftbot/config.dry.json `
  --strategy-list ClaudeBreakout ClaudeBreakoutRisk ClaudeBreakoutCorr `
                  ClaudeBreakoutPyramid ClaudeBreakoutChandelier ClaudeBreakoutPro `
  --timerange 20240601- --breakdown month

# Walk-forward hyperopt (optimise on history, validate untouched on a held-out period)
freqtrade hyperopt --userdir ftbot --config ftbot/config.dry.json `
  --hyperopt-loss CalmarHyperOptLoss --strategy ClaudeBreakoutHO `
  --timerange 20210101-20241231 --epochs 300 --spaces buy sell stoploss
```

**Decision rule:** keep a change only if it improves **Calmar on the validation period,
net of funding + slippage**, without breaking the drawdown gate. Adopt a parameter
*region*, not the single best epoch. Nothing here promotes to the live bot until the
Phase-3 window closes and the go-live gates pass (`OVERHAUL_PLAN.md` §4).
