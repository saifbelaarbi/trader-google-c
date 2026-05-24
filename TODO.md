# Trading Bot — Improvement Roadmap

**Last updated:** 2026-05-24
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

---

## HIGH PRIORITY — Do next

### H1 · Cloud Scheduler: reconcile cron (5 min)
Bybit handles TP/SL natively but gives no webhook callback. When TP/SL hits, Bybit closes the order but the Firestore position stays open as a ghost.
`/reconcile` already clears ghosts — it just needs to run on a schedule.

```bash
gcloud services enable cloudscheduler.googleapis.com --project=tradingbot-496815

gcloud scheduler jobs create http tradingbot-reconcile \
  --location=europe-west1 \
  --schedule="*/5 * * * *" \
  --uri="https://tradingbot-grpyjoqoaq-ew.a.run.app/reconcile" \
  --http-method=GET \
  --time-zone="UTC" \
  --project=tradingbot-496815
```

**Status:** [ ] TODO — 5 min to set up

---

### H2 · Daily loss limit (auto-pause)
If today's realized losses from `trade_log` exceed $20, set `_auto_trade_active = False` and Telegram-alert.
Check at the start of `_evaluate_and_trade()` before placing any new order.

**File:** `cloud/main.py` + `agent/state.py` (add `get_today_pnl()`)
**Status:** [ ] TODO

---

### H3 · Unrealized P&L in `agent/report.py`
For each open position, fetch current price via `broker.get_price(symbol)` and display:
```
BTCUSDT LONG | entry=$67,450 | now=$67,820 | P&L: +$0.55 (+1.85%)
```

**File:** `agent/report.py`
**Status:** [ ] TODO

---

### H4 · Anti-whipsaw cooldown
After a SL hit, pause new trades on that symbol for 30 minutes.
Store `cooldown_until` ISO timestamp in Firestore `config/{symbol}` document.
Check in `_evaluate_and_trade()` before evaluating signals.

**Files:** `cloud/main.py`, `agent/state.py` (add `get_config()` / `set_config()`)
**Status:** [ ] TODO

---

### H5 · Daily P&L summary via Telegram
Cloud Scheduler job at 23:55 UTC hits a `/daily-summary` endpoint that reads `trade_log` and sends:
```
📊 Daily — 2026-05-24
Trades: 4 | Won: 3 | Lost: 1
Realized P&L: +$2.85 | Win rate: 75%
Open positions: BTCUSDT LONG
```

**File:** `cloud/main.py` + Scheduler job
**Status:** [ ] TODO

---

## MEDIUM PRIORITY — Better signals

### M1 · 4H timeframe confirmation
Add TradingView alerts for BTCUSDT/ETHUSDT/SOLUSDT on the 4h chart.
Store with `timeframe="240"` in Firestore.
In `signals.evaluate()`: 4H EMA agrees → +10% size; disagrees → −30% size.

**Files:** `tradingview/SETUP.md`, `cloud/main.py` (accept tf=240), `agent/signals.py`
**Status:** [ ] TODO

---

### M2 · StochRSI + ADX (Pine Script + signals)
Add to `tradingview/indicators.pine`:
```pine
[stochRsiK, _] = ta.stoch(ta.rsi(close, 14), ta.rsi(close, 14), 14, 3)
smoothK = ta.sma(stochRsiK, 3)
[adxVal, diPlus, diMinus] = ta.dmi(14, 14)
```
Include `stoch_rsi_k` and `adx` in alert JSON.
Update `cloud/main.py` to store new fields.
Upgrade to 8-point scoring in `agent/signals.py`:
- StochRSI K > 20 and rising → bull point
- ADX > 25 → trending market (required for full score)

**Status:** [ ] TODO

---

### M3 · Correlation guard
Max 1 net-long position across {BTC, ETH, SOL} at a time.
Check in `agent/risk.py` `validate_decision()`.

**Status:** [ ] TODO

---

### M4 · Market regime detection
ATR(14)/EMA50 ratio for BTC on 1h:
- > 0.015 → trending → normal
- < 0.008 → ranging → skip non-BTC signals, reduce size 40%

**File:** `agent/signals.py` `evaluate()` — add at top before scoring
**Status:** [ ] TODO

---

## MEDIUM PRIORITY — Money management

### M5 · Bybit qty precision per symbol
Bybit requires symbol-specific qty rounding (BTC=0.001, ETH=0.01, SOL=0.1).
Fetch from `get_instruments_info()` and cache per session.

**File:** `agent/brokers/bybit.py` `place_market_order()` — replace `round(qty, 3)`
**Status:** [ ] TODO

---

### M6 · Partial take profit (scale out)
Two TP levels instead of one:
- TP1 at 1.0× ATR (50% of position) → close half
- TP2 at 2.0× ATR (remaining 50%) → let it run

**Files:** `agent/brokers/bybit.py`, `agent/executor.py`
**Status:** [ ] TODO

---

### M7 · Trailing stop loss
After price moves 1.5× ATR in our favor, trail SL at 0.5× ATR below peak.
Bybit supports this natively: `set_trading_stop(trailingStop=...)`.

**File:** `agent/brokers/bybit.py` — add `set_trailing_stop()` method
**Status:** [ ] TODO

---

## LOW PRIORITY — Analytics & reliability

### L1 · Trade performance stats (`agent/analytics.py`)
Read `trade_log` Firestore collection:
```bash
python -m agent.analytics --days 30
```
Output: total P&L, win rate, avg R:R, max drawdown, per-symbol breakdown.
**Status:** [ ] TODO

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
```
GET /pnl?days=7
→ { "realized": 4.25, "trades": 12, "win_rate": 0.67, "by_symbol": {...} }
```
**File:** `cloud/main.py`
**Status:** [ ] TODO

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
This week
  [H1] Cloud Scheduler reconcile cron          5 min
  [H2] Daily loss limit                        15 min
  [M5] Bybit qty precision lookup              20 min
  [H3] Unrealized P&L in report               20 min

Next week
  [H4] Anti-whipsaw cooldown                  25 min
  [M2] StochRSI + ADX                         1-2h
  [M1] 4H timeframe confirmation              1h
  [M3] Correlation guard                      20 min

Week 3
  [M6] Partial take profit                    1h
  [M7] Trailing stop                          30 min
  [H5] Daily P&L Telegram summary            30 min

Week 4+
  [L1] Trade analytics                        1-2h
  [L3] Backtester                             2-3h
  [L2] Dead man's switch                      30 min
```
