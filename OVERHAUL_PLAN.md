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
