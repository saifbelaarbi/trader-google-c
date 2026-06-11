# Trading Bot — Improvement Roadmap

> **⚠️ SUPERSEDED for strategy work:** the system is migrating to a Freqtrade
> backbone for backtesting + paper trading on the user's PC. See
> **`OVERHAUL_PLAN.md`** and **`ftbot/SETUP.md`**. Items below remain valid for
> the legacy GCP stack until Phase 5 cleanup.

**Last updated:** 2026-06-11 (overhaul session)
**Current state:** Cloud Run relay live · Bybit testnet connected · Telegram working · Claude is the trading brain
**Broker:** Bybit USDT perpetuals (testnet). Supports longs + shorts + native TP/SL.

Legend: ✅ Done · [ ] TODO

---

## COMPLETED (do not redo)

| # | What | How |
|---|------|-----|
| ✅ | Telegram bot live (`saif_trader_bot`) | Token + chat_id hardcoded in setup-session.sh |
| ✅ | Telegram commands: /status /positions /close /pause /resume /help | `cloud/main.py` telegram-webhook handler |
| ✅ | Telegram trade notifications on auto-open/close/error | `cloud/telegram.py` |
| ✅ | Cloud Run deployed + healthy | `https://tradingbot-grpyjoqoaq-ew.a.run.app` |
| ✅ | Auto-execute thread in Cloud Run (off by default, toggle via /resume) | `cloud/main.py` `_evaluate_and_trade()` |
| ✅ | `/state` endpoint — positions + 32 bars per symbol | `cloud/main.py` |
| ✅ | `/indicators/<symbol>` endpoint | `cloud/main.py` |
| ✅ | `/reconcile` endpoint — clears ghost Firestore positions | `cloud/main.py` |
| ✅ | Firestore REST API (gRPC blocked in Claude Code container) | `agent/state.py` full rewrite |
| ✅ | Bybit broker (USDT perps, supports_short, manages_tp_sl_natively) | `agent/brokers/bybit.py` |
| ✅ | Broker ABC + factory pattern (BROKER env var) | `agent/brokers/base.py`, `agent/brokers/__init__.py` |
| ✅ | `agent/report.py` — live indicator + signal report | `python -m agent.report` |
| ✅ | `agent/executor.py` — Claude's trade tool | `python -m agent.executor open/close/positions` |
| ✅ | MACD acceleration check (positive AND growing) | `agent/signals.py` |
| ✅ | EMA20 slope filter (sloping up/down, not just crossover) | `agent/signals.py` |
| ✅ | Dynamic ATR-based position sizing (scales with signal score) | `agent/signals.py` |
| ✅ | Risk gate validates every decision (size cap, TP/SL ratio, SL max) | `agent/risk.py` |
| ✅ | SA key in repo (`sa-key.json`) — auto-loaded by setup-session.sh | `.gitignore` exception added |
| ✅ | Session auto-start: env, deps, Telegram ping | `.claude/setup-session.sh` |
| ✅ | CLAUDE.md — full trading brain instructions for Claude | `CLAUDE.md` |
| ✅ | CI passes (pytest + ruff) → auto-deploy on push to main | `.github/workflows/deploy.yml` |
| ✅ | Cloud Run min-instances=1, memory=512Mi | `deploy.yml` |
| ✅ | Health endpoint: returns mode, auto_trade, min_signals, role | `cloud/main.py` |
| ✅ | Pre-approved commands (no permission prompts for agent commands) | `.claude/settings.json` |
| ✅ | SA key embedded as base64 in setup-session.sh — no file in repo | `.claude/setup-session.sh` |
| ✅ | Cloud Run URL auto-fetched from Firestore at session start | `.claude/setup-session.sh`, `deploy.yml` |
| ✅ | H2 · Daily $20 loss limit — auto-pauses auto-trade + Telegram alert | `cloud/main.py`, `agent/state.py` |
| ✅ | H3 · Unrealized P&L in report — live price + $ + % per position | `agent/report.py` |
| ✅ | H4 · Anti-whipsaw cooldown — 30 min pause after SL hit, Firestore-backed | `cloud/main.py`, `agent/state.py` |
| ✅ | H5 · Daily P&L summary — `/daily-summary` endpoint + 23:55 UTC scheduler | `cloud/main.py`, `deploy.yml` |
| ✅ | H1 · Cloud Scheduler reconcile cron — auto-created/updated on each deploy | `deploy.yml` |
| ✅ | M5 · Bybit qty precision — fetches qtyStep per symbol, rounds correctly | `agent/brokers/bybit.py` |
| ✅ | TP/SL hard limits removed — risk gate only enforces size cap + symbol guard | `agent/risk.py`, `agent/signals.py` |
| ✅ | No-code rule added to CLAUDE.md — agents must not touch code without permission | `CLAUDE.md` |
| ✅ | M2 · StochRSI + ADX — 8-point scoring, Pine Script updated, ADX bug fixed | `agent/signals.py`, `tradingview/indicators.pine` |
| ✅ | M4 · Market regime detection — ATR/EMA50 ratio, ranging/trending thresholds | `agent/signals.py` |
| ✅ | M6 · Partial take profit — TP1 at 1×ATR (50%), TP2 at 2×ATR, Bybit partial mode | `agent/brokers/bybit.py`, `agent/executor.py`, `cloud/main.py` |
| ✅ | M7 · Trailing stop — 0.5×ATR trail, activates at 1.5×TP1, Bybit native | `agent/brokers/bybit.py`, `agent/brokers/base.py` |
| ✅ | L1 · Trade analytics — `python -m agent.analytics --days 30` | `agent/analytics.py` |
| ✅ | L4 · `/pnl` API endpoint — `GET /pnl?days=7` | `cloud/main.py` |

---

## MEDIUM PRIORITY — Better signals

---

## MANUAL SETUP — One-time Cloud Shell steps

### S1 · Enable Cloud Scheduler + grant SA permissions
The SA used by GitHub Actions can't enable APIs or create scheduler jobs.
Run once from Cloud Shell, then deploys will manage job URLs automatically.

```bash
# Enable Cloud Scheduler API
gcloud services enable cloudscheduler.googleapis.com --project=tradingbot-496815

# Grant SA permission to manage scheduler jobs
gcloud projects add-iam-policy-binding tradingbot-496815 \
  --member="serviceAccount:tradingbot-sa@tradingbot-496815.iam.gserviceaccount.com" \
  --role="roles/cloudscheduler.admin"
```

After running the above, re-add the scheduler create/update block to `deploy.yml`
(it was removed because it failed without this permission).

**Status:** [ ] TODO — 2 min in Cloud Shell

---

## MEDIUM PRIORITY — Better signals

### M1 · 4H timeframe confirmation
**Status:** [ ] TODO
Add TradingView alerts for BTCUSDT/ETHUSDT/SOLUSDT on the 4h chart.
Store with `timeframe="240"` in Firestore.
In `signals.evaluate()`: 4H EMA agrees → +10% size; disagrees → −30% size.

**Files:** `tradingview/SETUP.md`, `cloud/main.py` (accept tf=240), `agent/signals.py`
**Status:** [ ] TODO

---

### M2 · StochRSI + ADX (Pine Script + signals)
**Status:** ✅ Done

---

### M3 · Correlation guard
Max 1 net-long position across {BTC, ETH, SOL} at a time.
Check in `agent/risk.py` `validate_decision()`.

**Status:** [ ] TODO

---

### M4 · Market regime detection
**Status:** ✅ Done

---

## MEDIUM PRIORITY — Money management

### M5 · Bybit qty precision per symbol
**Status:** ✅ Done

---

### M6 · Partial take profit (scale out)
**Status:** ✅ Done

---

### M7 · Trailing stop loss
**Status:** ✅ Done

---

## LOW PRIORITY — Analytics & reliability

### L1 · Trade performance stats (`agent/analytics.py`)
**Status:** ✅ Done — `python -m agent.analytics --days 30`

---

### L2 · Dead man's switch
Cloud Scheduler checks every 10 min: if no alert for a tracked symbol in >30 min during 08:00–20:00 UTC → Telegram warning.
**File:** new Cloud Scheduler job → `/heartbeat-check` endpoint
**Status:** [ ] TODO

---

### L3 · Backtester
Replay stored Firestore `alerts` collection to simulate signal history:
```bash
python -m agent.backtest --symbol BTCUSDT --from 2026-05-20
```
**Status:** [ ] TODO

---

### L4 · `/pnl` API endpoint
**Status:** ✅ Done — `GET /pnl?days=7`

---

## FUTURE — Live trading migration

Do only after ≥14 days of profitable testnet results (win rate > 55%, avg R:R > 1.5).

- [ ] Review 14-day trade log: win rate > 55%, avg R:R > 1.5
- [ ] Get live Bybit API keys (https://bybit.com → API Management)
- [ ] Update secrets: `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `TRADING_MODE=live`
- [ ] Start with 50% position sizes for the first week
- [ ] Set `MAX_DAILY_LOSS_USDT = 15` (conservative)
- [ ] Test 1 trade manually before enabling auto-trade
- [ ] Monitor first 5 live trades closely via Telegram

---

## RECOMMENDED ORDER

```
✅ DONE
  [H1] Cloud Scheduler reconcile cron
  [H2] Daily loss limit
  [H3] Unrealized P&L in report
  [H4] Anti-whipsaw cooldown
  [H5] Daily P&L Telegram summary
  [M2] StochRSI + ADX (8-point scoring)
  [M4] Market regime detection
  [M5] Bybit qty precision
  [M6] Partial take profit
  [M7] Trailing stop
  [L1] Trade analytics (agent/analytics.py)
  [L4] /pnl API endpoint

Next
  [S1] Cloud Shell: enable Cloud Scheduler + grant SA permissions  (2 min, manual)
  [M1] 4H timeframe confirmation                                   (1h)
  [L2] Dead man's switch (needs S1 first)                          (30 min)
  [L3] Backtester                                                   (2-3h)

Skipped
  [M3] Correlation guard — not needed for now
```
