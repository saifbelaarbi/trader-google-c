# Claude Code — Trading System Instructions

**Architecture changed 2026-06-12** (see `OVERHAUL_PLAN.md` for the full campaign log).
Freqtrade is now the trading engine; Claude is the research and operations layer.
The old "Claude is the trading brain / execute via agent.executor" workflow is RETIRED.

---

## Current state (as of 2026-06-12)

- **Phase 3 — paper trading in progress.** `ClaudeBreakout` (4h Donchian breakout,
  9 USDT-perp pairs, max 4 positions, $200 dry-run wallet) runs 24/7 in Freqtrade
  dry-run mode **on the user's PC**, with its own Telegram bot for monitoring.
- Started: 2026-06-12. Gates before real money: ≥4 weeks AND ≥30 closed trades,
  PF ≥ 1.3 or backtest-consistent behavior, max drawdown ≤ ~26%.
- Backtest reference (2024-06 → 2026-06): +40.9%, PF 1.15, win rate 30.8%,
  max DD 25.9%, ~0.8 trades/day. Losing streaks of 20+ are within norms.
- Strategy choice was pre-registered (default params; all 4 parameter neighbors
  also profitable, PF 1.13–1.31). Do NOT switch to an in-sample-best variant.

## Division of labor

| Layer | Owner |
|---|---|
| Per-candle decisions, execution, stops/exits | Freqtrade `ClaudeBreakout` on the PC |
| Phone monitoring, kill switch | Freqtrade Telegram bot (`/status /profit /stats /pause /forceexit`) |
| Strategy R&D: backtests, analysis, iteration | Claude Code sessions (this repo) |
| Legacy signal pings + Firestore journal | Old GCP stack (unchanged, to be retired in Phase 5) |

## What Claude sessions do now

1. **Weekly review** (primary ritual): user pastes `/profit`, `/stats`,
   `/performance` output or the sqlite trade log
   (`ftbot/tradesv3.dryrun.sqlite`). Compare against the backtest profile above:
   win rate ~30%, winners avg ~+5% over ~6 days via Donchian exit, losers
   ~-4% (stop/trail). Flag divergence; do not propose parameter tweaks
   mid-test — that invalidates the experiment.
2. **Incident response**: freqtrade errors/tracebacks, Telegram issues,
   restart problems. The bot is started via `ftbot/start-bot.bat`
   (pulls main, preserves local config secrets, launches).
3. **Research for AFTER the test**: hyperopt prep (slow-parameter gradient
   looked promising: 30/15 windows, EMA250), longer-history validation,
   universe expansion. Backtests run on the user's PC — this cloud
   environment cannot reach exchange APIs or run freqtrade.
4. **Cloud sessions** (`CLOUD SESSION: yes` in banner): analysis/planning only.
   Bybit and market-data APIs are blocked here.

## Key commands (user's PC, repo root)

```powershell
ftbot\start-bot.bat                  # pull main + start paper bot (one click, one-shot)
ftbot\watch-bot.bat                  # same, but auto-redeploys on each main push touching ftbot/ (dry-run only)
freqtrade backtesting --userdir ftbot --config ftbot/config.dry.json --strategy ClaudeBreakout --timerange 20240601- --breakdown month
freqtrade download-data --userdir ftbot --config ftbot/config.dry.json --timeframes 4h --timerange 20240101-
```

`ftbot/config.dry.json` in the working tree contains local secrets (Telegram
token, jwt) — never commit the user's filled-in values; repo keeps placeholders.

## Strategy files (ftbot/strategies/)

- `ClaudeBreakout.py` — ACTIVE. V4 Donchian 20/10 + EMA200 filter + breakout
  radar (Telegram push each 4h candle: per-pair bias + distance to trigger).
- `breakout_variants.py` — parameter neighbors for robustness checks.
- `ClaudeConsensus.py`, `ClaudePullback.py`, `ClaudeTrend1h.py` — V1–V3,
  kept as the rejected-premise record (all backtest-negative; see
  OVERHAUL_PLAN.md results log). Do not trade them.

## ⛔ ABSOLUTE RULE — NO CODE CHANGES WITHOUT EXPLICIT PERMISSION

**You must NEVER edit files, write code, create branches, or open PRs unless the user
explicitly says at the start of the session: "we are going to code" (or equivalent).**

Default session mode is **analysis only**: review bot performance, analyze results,
answer questions. Do not improve, refactor, fix, or touch the codebase unless coding
is explicitly authorized. If you notice a bug or improvement, note it in chat —
do not act on it.

This rule exists because autonomous code changes caused unintended PRs and branch pollution.

Additionally, even when coding is authorized: never change `ClaudeBreakout`
parameters or trading logic during the paper-trading window without explicit
user sign-off, and keep the go-live gates intact — they are the profit plan.

## Legacy GCP stack (Phase 5: retire after live is stable)

Still deployed and untouched: Cloud Run relay (`tradingbot-grpyjoqoaq-ew.a.run.app`),
Firestore journal (`tradingbot-496815`), old Telegram bot (`saif_trader_bot`,
webhook-bound — its token must NOT be reused by freqtrade), TradingView webhooks,
`agent/` CLI tools (`python -m agent.report` etc. still work for the old stack).
