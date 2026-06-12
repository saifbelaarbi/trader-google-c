# System Overhaul — Freqtrade Backbone

**Goal:** prove (or disprove) the strategy's edge with real backtests and 24/7 paper
trading on your PC, then graduate to real money behind hard gates.

**Architecture decision:** adopt [Freqtrade](https://www.freqtrade.io) as the
execution + testing engine. The custom stack's structural flaws for profitability:

1. **No backtesting** — the 8-point engine has never been validated on history.
2. **Trades require an open Claude session** — no session, no brain, missed moves.
3. **TradingView → Cloud Run → Firestore pipeline** is a fragile dependency chain
   just to get OHLCV indicators that ccxt provides directly.
4. **Custom Telegram/risk/analytics code** re-implements what Freqtrade ships
   battle-tested: dry-run mode, Telegram bot, protections, hyperopt, FreqUI.

**New division of labor:**

| Layer | Owner |
|---|---|
| Per-candle decisions, execution, stops, TP | Freqtrade (`ClaudeConsensus` strategy) on your PC |
| Phone monitoring + kill switch | Freqtrade's native Telegram bot |
| Strategy R&D: backtests, hyperopt, edge analysis, code iteration | Claude Code sessions |
| Signal pings / legacy journal | Existing GCP stack (unchanged, retire later) |

---

## Phases

### Phase 0 — Scaffold ✅ (this PR)
- `ftbot/strategies/ClaudeConsensus.py` — faithful port of `agent/signals.py`:
  8-point consensus, regime detection, confidence-scaled sizing, ATR SL,
  TP1 partial (1×ATR, 50%), TP2 (2×ATR), 0.5×ATR trail, consensus-flip exit,
  CooldownPeriod / StoplossGuard / MaxDrawdown protections (H2+H4 equivalents).
- `ftbot/config.dry.json` — Bybit futures, $200 dry-run wallet, max 2 positions.
- `ftbot/SETUP.md` — PC install + run guide.

### Phase 1 — Reality check (first week)
- Install on PC, download 2024→now 15m/1h Bybit data, run the first backtest.
- **Expect the unvarnished number.** If the strategy loses on history, that is
  the system working — better to learn it here than with deposits.
- Claude session: analyze results, identify the biggest leak (entries? exits?
  regime filter? a specific pair?).

### Phase 2 — Iterate until backtest-positive
- Convert thresholds to hyperopt parameters (`min_signals`, RSI zones, ATR
  multipliers, regime cutoffs, signal weights).
- Hyperopt with walk-forward split: optimize on 2024, validate on 2025+.
  **Never trust parameters that only work on the data they were fit to.**
- Target before proceeding: ≥100 trades in validation period, profit factor
  ≥ 1.3 **after fees**, max drawdown ≤ 15%.

### Results log — strategy campaign of 2026-06-12

All backtests: Bybit USDT futures, 2024-06-01 → 2026-06-12, $200 start, 0.06% fee.
Market change over the period: ≈ -28% to -41% depending on universe.

| Version | Premise | Universe | Result | Verdict |
|---|---|---|---|---|
| V1 ClaudeConsensus | 8-pt consensus, 15m | 3 pairs | -96.8%, PF 0.40 | dead: fee churn + stops in noise + inverted confluence |
| V2 ClaudePullback | pullback-to-trend, 15m | 3 pairs | -76.7%, PF 0.51 | dead: 15m fee math can't close |
| V3 ClaudeTrend1h | same premise, 1h/4h | 3 pairs | -29.6%, PF 0.75 | dead: winners capped, losers full-size |
| V4 ClaudeBreakout | Donchian 20/10 + EMA200, 4h | 3 pairs | +0.2%, PF 1.00 | breakeven — needs breadth |
| V4 ClaudeBreakout | same | **9 pairs, 4 slots** | **+40.9%, PF 1.15, DD 26%** | **edge** |

Robustness (9 pairs, all parameter neighbors profitable → structural edge):

| Variant | Profit | PF | Max DD |
|---|---|---|---|
| 20/10, EMA200 (default) | +40.9% | 1.15 | 25.9% |
| Fast 15/8 | +40.1% | 1.13 | 29.2% |
| Slow 30/15 | +73.8% | 1.31 | 22.7% |
| EMA150 | +37.2% | 1.13 | 29.6% |
| EMA250 | +63.0% | 1.25 | 20.3% |

**Decision:** paper trade `ClaudeBreakout` (default params — chosen before seeing
results; switching to the in-sample best would re-introduce selection bias).
Slower-parameter gradient is a hyperopt direction after paper trading validates
backtest-vs-reality. Expected live profile: ~0.8 trades/day across 9 pairs,
~30% win rate, P&L carried by multi-day winners, drawdowns to ~26% and losing
streaks past 20 are within backtest norms — not a malfunction.

### Phase 3 — Paper trading (≥4 weeks)
- `freqtrade trade` dry-run on PC, 24/7, Telegram on phone.
- Weekly Claude review: dry-run vs backtest drift, edge concentration,
  one hypothesis tweak per week max (no constant fiddling).

### Phase 4 — Go-live gates (ALL must pass)
- [ ] ≥4 weeks dry-run, ≥30 closed trades
- [ ] Dry-run profit factor ≥ 1.3, win rate within ~10pts of backtest
- [ ] Max dry-run drawdown ≤ 15% of wallet
- [ ] No unexplained divergence between backtest and dry-run behavior
- Then: live Bybit keys, start with $50–100 (not the full intended capital),
  position sizes halved for the first 2 weeks, `MaxDrawdown` protection tightened.

### Phase 5 — Cleanup (after live is stable)
- Retire TradingView webhooks + Cloud Run auto-trade path.
- Keep or fold: Firestore journal, old Telegram bot, `agent/` CLI tools.
- Rewrite `CLAUDE.md` for the new architecture (Claude = research layer).

---

## Honest framing (read once, then it's never mentioned again)

No architecture makes a strategy profitable — it only makes profitability
*measurable*. Dry-run always flatters: real fills have slippage, funding costs,
and fee drag that backtests underestimate. The gates above exist because the
fastest way to lose the eventual real bankroll is to skip them. Risk limits in
the strategy (max 2 positions, drawdown guard, cooldowns) are kept not as rules
for their own sake but because surviving losing streaks is a precondition for
collecting on winning ones.
