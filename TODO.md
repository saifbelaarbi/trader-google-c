# Trading Bot — Full Improvement Roadmap

**Last updated:** 2026-05-23  
**Current state:** Working relay + rule-based signals + human-confirmed execution (testnet)  
**Goal:** Fully autonomous, real-time, profitable, self-monitoring trading system

---

## CRITICAL — THE THREE PROBLEMS TO FIX FIRST

These are the root causes of missed gains and slow execution:

| # | Problem | Root Cause | Impact |
|---|---------|-----------|--------|
| P1 | **Permission prompts block execution** | Claude Code asks confirmation for every bash command | Trade missed while waiting for click |
| P2 | **30-second polling lag** | `agent/main.py` sleeps 30s between checks | Signal detected up to 30s late |
| P3 | **Human-in-the-loop bottleneck** | Trades only execute when Claude Code session is open + user confirms | Session closed = zero trades |

**Fix P1 immediately** → add `.claude/settings.json` (see Section 1 below)  
**Fix P2 + P3** → move auto-execution to Cloud Run (see Section 2 below)

---

## SECTION 1 — PERMISSIONS & AUTONOMY IN CLAUDE CODE [ HIGH PRIORITY ]

### 1.1 Pre-approve all agent commands (fixes P1)
**File to create:** `.claude/settings.json`

Pre-approve these patterns so Claude Code never asks for permission:
- `python -m agent.report`
- `python -m agent.executor *`
- `python -m agent.main`
- Read-only Firestore / GCP commands

**Status:** [ ] TODO

### 1.2 Update CLAUDE.md to be more autonomous
- Add explicit instruction: "When bull_signals ≥ 5 AND vol_ratio > 1.3, execute without waiting for confirmation"
- Add explicit instruction: "When position is open and opposite signals ≥ 4, close immediately"
- Define "high confidence" vs "needs review" tiers

**Status:** [ ] TODO

### 1.3 Auto-session trigger via Cloud Scheduler
- Set up Cloud Scheduler to call a `/session-report` endpoint every 15m
- Endpoint runs report + evaluates signal + if actionable → sends Telegram alert
- This replaces the need for the user to manually open Claude Code

**Status:** [ ] TODO

---

## SECTION 2 — AUTONOMOUS EXECUTION ON CLOUD RUN [ HIGH PRIORITY — BIGGEST GAIN ]

Currently trades only execute during an open Claude Code session with human confirmation.  
**Target:** Trades fire within 5 seconds of TradingView alert arriving, 24/7.

### 2.1 Add auto-executor to Cloud Run webhook handler
**File:** `cloud/main.py`

When a webhook arrives:
1. Store alert in Firestore (existing behavior)
2. Fetch last 32×15m + 8×1h alerts for that symbol
3. Run `signals.evaluate()` immediately
4. If action = OPEN_LONG/OPEN_SHORT with bull/bear ≥ 5 → execute trade automatically
5. If action = CLOSE → close position automatically
6. Log decision to Firestore `auto_decisions` collection
7. Send Telegram notification (see Section 4)

**Risk guard:** Only auto-execute if `AUTO_TRADE_ENABLED=true` env var is set (off by default, toggle from Telegram)

**Status:** [ ] TODO

### 2.2 Migrate broker.py to Cloud Run
- Move `agent/broker.py` to `cloud/broker.py` (or shared `lib/broker.py`)
- Cloud Run needs Binance API keys from Secret Manager (already stored there)
- Mount secrets: `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `TRADING_MODE`

**Status:** [ ] TODO

### 2.3 Add `/execute` endpoint for manual triggers
```
POST /execute
{ "symbol": "BTCUSDT", "action": "OPEN_LONG", "size_usdt": 30 }
```
Secured with webhook secret. Allows Telegram bot or cron to trigger execution.

**Status:** [ ] TODO

### 2.4 Firestore real-time listener (replaces 30s polling)
Replace `agent/main.py` polling loop with `on_snapshot` Firestore listener:
```python
db.collection("alerts").where("symbol", "==", sym).on_snapshot(callback)
```
Reacts in <1s instead of up to 30s. Only needed if keeping local agent.

**Status:** [ ] TODO

---

## SECTION 3 — TELEGRAM BOT INTEGRATION [ HIGH PRIORITY ]

You want to control and monitor the bot without opening your laptop.  
Telegram is the best option: free, has bots API, works on mobile, better than WhatsApp for automation.

### 3.1 Create Telegram bot
1. Open Telegram → search @BotFather → `/newbot`
2. Copy the bot token
3. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to GCP Secret Manager
4. Mount secrets to Cloud Run

**Status:** [ ] TODO

### 3.2 Notification events
Send Telegram message on every event:

| Event | Message Example |
|-------|-----------------|
| Trade opened | `🟢 BTCUSDT LONG opened @ $67,450 | SL: $66,920 | TP: $68,360 | Size: $30` |
| Trade closed (TP) | `✅ BTCUSDT TP hit @ $68,360 | +$1.35 profit` |
| Trade closed (SL) | `🔴 BTCUSDT SL hit @ $66,920 | -$0.78 loss` |
| Trade closed (manual) | `📤 BTCUSDT manually closed @ $67,800` |
| Signal detected | `📡 BTCUSDT: 5/6 BULL signals | RSI=58 | MACD↑ | vol×1.4` |
| No webhook in >30min | `⚠️ BTCUSDT: No alerts received in 30 min — TradingView may be down` |
| Bot error | `🚨 Error in executor: {error message}` |

**Status:** [ ] TODO

### 3.3 Telegram command interface
Make the bot respond to commands:

| Command | Action |
|---------|--------|
| `/positions` | Show all open positions with unrealized P&L |
| `/report` | Full indicator report for all symbols |
| `/report BTCUSDT` | Single symbol report |
| `/close BTCUSDT` | Close position immediately |
| `/pause` | Set `AUTO_TRADE_ENABLED=false` in Firestore config |
| `/resume` | Re-enable auto trading |
| `/status` | Bot health, last webhook time, current mode |
| `/pnl` | Today's realized P&L from trade_log |
| `/help` | Command list |

**Implementation:** Cloud Run `/telegram-webhook` endpoint receives Telegram updates (set via `setWebhook`).

**Status:** [ ] TODO

### 3.4 Daily P&L summary (scheduled)
Every day at 23:55 UTC, send:
```
📊 Daily Summary — 2026-05-23
Trades: 4 | Won: 3 | Lost: 1
Realized P&L: +$2.85
Win rate: 75% | Avg R:R: 1.8
Open positions: BTCUSDT LONG (unrealized: +$0.42)
```

**Status:** [ ] TODO

---

## SECTION 4 — INDICATOR IMPROVEMENTS [ MEDIUM PRIORITY ]

Current set: EMA20, EMA50, RSI14, MACD(12,26,9), ATR14, VolRatio  
These are good but can be improved significantly.

### 4.1 Add Stochastic RSI (Pine Script)
StochRSI(14,3,3) — faster and more sensitive than RSI alone.
- StochRSI K > 20 and rising → bullish signal
- StochRSI K < 80 and falling → bearish signal
- Filters RSI false signals in ranging markets

**File:** `tradingview/indicators.pine`  
**Status:** [ ] TODO

### 4.2 Add Bollinger Bands (Pine Script)
BB(20, 2.0) — detects volatility squeezes and breakouts.
- Price above upper BB and vol > 1.5 → strong breakout (extra bull signal)
- Price below lower BB and vol > 1.5 → strong breakdown (extra bear signal)
- BB width < recent average → squeeze forming (reduce position size)

**File:** `tradingview/indicators.pine`  
**Status:** [ ] TODO

### 4.3 Add ADX trend strength filter
ADX(14) — filters out choppy, ranging markets.
- ADX > 25 → trending market, signals reliable
- ADX < 20 → ranging market, SKIP signal regardless of score
- +DI > -DI → uptrend confirmation

This alone would have prevented many false signals in sideways markets.

**File:** `tradingview/indicators.pine`  
**Status:** [ ] TODO

### 4.4 Add 4H timeframe confirmation
Add 2 more TradingView alerts (BTCUSDT 4h, ETHUSDT 4h, SOLUSDT 4h) for higher-timeframe bias.
- 4H EMA trend agrees with 15m signal → score += 1 (extra conviction)
- 4H EMA trend disagrees → reduce size_usdt by 30%

**Status:** [ ] TODO

### 4.5 Update signals.py — 8-point scoring system
Replace current 6-point with 8-point using new indicators:
```
Bull signals (0-8):
  1. EMA20 > EMA50 on 15m
  2. EMA20 > EMA50 on 1h  
  3. 50 < RSI14 < 70
  4. MACD hist > 0 AND increasing (not just positive)
  5. vol_ratio > 1.3
  6. StochRSI K > 20 and rising
  7. Price > BB upper (breakout) OR price bouncing off BB mid
  8. ADX > 25 (trending)

Threshold: ≥ 6/8 for auto-execute | ≥ 5/8 for signal alert
```

**File:** `agent/signals.py`  
**Status:** [ ] TODO

### 4.6 MACD momentum acceleration check
Current check: `macd > 0` (just positive)  
Better check: `macd > 0 AND macd > prev_macd` (positive AND growing)  
This catches the acceleration phase, not just flat positive MACD.

**File:** `agent/signals.py:39`  
**Status:** [ ] TODO

### 4.7 EMA slope filter
Instead of just EMA20 > EMA50, also check that EMA20 is sloping upward:
`ema20[-1] > ema20[-2] > ema20[-3]` (last 3 bars trending up)  
This eliminates flat EMA crossovers that quickly reverse.

**File:** `agent/signals.py`  
**Status:** [ ] TODO

---

## SECTION 5 — STRATEGY & MONEY MANAGEMENT [ HIGH PRIORITY ]

### 5.1 Dynamic position sizing (ATR-based Kelly)
Current: fixed $30 per trade  
Better: size based on signal confidence + ATR volatility

```python
base_size = 25  # USDT
confidence_multiplier = bull_count / 8  # 0.625 → 1.0
atr_multiplier = min(1.0, 0.5 / sl_pct)  # smaller when volatile
size_usdt = base_size * confidence_multiplier * atr_multiplier
size_usdt = max(15, min(40, size_usdt))  # clamp $15-$40
```

**File:** `agent/signals.py`  
**Status:** [ ] TODO

### 5.2 Partial take profit (scale out)
Instead of one TP order, use two:
- TP1 at 1.0 × ATR (50% of position) → close half, book profit
- TP2 at 2.0 × ATR (remaining 50%) → let it run

On Binance Futures: place two reduce-only orders at different prices.

**File:** `agent/broker.py`, `agent/executor.py`  
**Status:** [ ] TODO

### 5.3 Trailing stop loss
After TP1 is hit, move SL to breakeven (entry price).  
After price moves 1.5× ATR in our favor, trail SL at 0.5× ATR below peak.

**Implementation:** Cloud Scheduler job every 5min checks open positions vs current price via Binance API, adjusts SL order.

**File:** new `cloud/trailing_stop.py`  
**Status:** [ ] TODO

### 5.4 Daily loss limit (auto-pause)
Config: `MAX_DAILY_LOSS_USDT = 20`  
Logic: Sum today's realized losses from `trade_log`. If sum > limit → set `AUTO_TRADE_ENABLED=false` + send Telegram alert.  
Resets at 00:00 UTC.

**Status:** [ ] TODO

### 5.5 Correlation guard
Don't open LONG on BTCUSDT and ETHUSDT simultaneously (they move together).  
Rule: Only 1 long position per correlated group {BTC, ETH, SOL} at a time.  
Exception: Allow if they have different signal strengths (one at 7/8, other at 4/8).

**File:** `agent/risk.py`  
**Status:** [ ] TODO

### 5.6 Market regime detection
Before any trade, check if BTC is in a trending or ranging regime:
- BTC ATR(14) / EMA50 > 0.015 → trending regime → trade normally
- BTC ATR(14) / EMA50 < 0.008 → ranging regime → skip non-BTC trades, reduce size

**File:** `agent/signals.py`  
**Status:** [ ] TODO

### 5.7 Session-based trading hours filter
Crypto volumes are highest during:
- London open: 08:00–12:00 UTC
- US open: 13:30–17:30 UTC
- Asia open: 00:00–04:00 UTC

Optional: reduce position size by 40% outside these windows. Avoid 20:00–23:00 UTC (thin liquidity).

**Status:** [ ] TODO

### 5.8 Anti-whipsaw cooldown
After a SL is hit, pause trading on that symbol for 30 minutes.  
Prevents re-entering immediately into the same choppy move.

**Status:** [ ] TODO

---

## SECTION 6 — P&L TRACKING & ANALYTICS [ MEDIUM PRIORITY ]

### 6.1 Real-time unrealized P&L in report
`python -m agent.report` should show for each open position:
```
BTCUSDT LONG | entry=$67,450 | current=$67,820 | P&L: +$0.55 (+1.85%) | R: +0.89
```
Requires fetching current price from Binance (or latest Firestore alert).

**File:** `agent/report.py`  
**Status:** [ ] TODO

### 6.2 Trade performance stats
Calculate and display rolling stats:
- Total realized P&L (all time, last 7 days, last 30 days)
- Win rate (%)
- Average R won / average R lost
- Largest win / largest loss
- Sharpe ratio (simplified: avg return / std dev)
- Max drawdown

**Source:** `trade_log` Firestore collection  
**File:** new `agent/analytics.py`  
**Status:** [ ] TODO

### 6.3 Per-symbol performance breakdown
Show stats separately for BTCUSDT, ETHUSDT, SOLUSDT.  
Helps identify which symbols are profitable vs which to drop.

**Status:** [ ] TODO

### 6.4 `/pnl` API endpoint on Cloud Run
```
GET /pnl?days=7
→ { "realized": 4.25, "trades": 12, "win_rate": 0.67, "by_symbol": {...} }
```

**Status:** [ ] TODO

---

## SECTION 7 — INFRASTRUCTURE & RELIABILITY [ MEDIUM PRIORITY ]

### 7.1 Cloud Run min-instances = 1
Current: Cloud Run scales to 0 between requests (cold start = 2-3s).  
Fix: Set `--min-instances=1` to keep one instance warm.  
Cost: ~$4/month extra. Worth it for a trading bot.

**File:** `.github/workflows/deploy.yml` or `cloudbuild.yaml`  
**Status:** [ ] TODO

### 7.2 Dead man's switch — webhook health monitor
Cloud Scheduler pings a `/heartbeat-check` endpoint every 10 minutes.  
Endpoint checks: last webhook received per symbol. If any symbol has no alert in >30 min during market hours → send Telegram alert.

**Status:** [ ] TODO

### 7.3 Binance lot size precision lookup
Current: hardcoded `round(qty, 3)` in `broker.py:43`  
Better: call `futures_exchange_info()` to get exact `stepSize` per symbol.  
This prevents order rejections when adding new symbols (SOLUSDT needs 1dp precision).

**File:** `agent/broker.py`  
**Status:** [ ] TODO

### 7.4 Graceful retry on Binance API errors
Binance API occasionally returns 429 (rate limit) or 500 (server error).  
Add exponential backoff: retry 3 times with 1s, 2s, 4s delays.

**File:** `agent/broker.py:27`  
**Status:** [ ] TODO

### 7.5 Position reconciliation on Cloud Run
Add `/reconcile` endpoint (already referenced in COWORK_HANDOFF.md) that:
1. Fetches all positions from Firestore
2. Fetches actual positions from Binance
3. Clears "ghost" Firestore positions where Binance shows no open position
4. Alerts via Telegram if discrepancy found

Schedule via Cloud Scheduler every 5 minutes.

**Status:** [ ] TODO

### 7.6 Structured logging + Cloud Monitoring
Add request latency, signal counts, and trade counts as Cloud Monitoring custom metrics.  
Set alert policy: if error rate > 5% in 5min window → Telegram alert.

**Status:** [ ] TODO

### 7.7 Health check improvements
Current `/health` just returns `{"status": "ok"}`.  
Improve to check actual dependencies:
```json
{
  "status": "ok",
  "firestore": "connected",
  "last_alert_btc_age_seconds": 480,
  "open_positions": 1,
  "auto_trade": true
}
```

**File:** `cloud/main.py`  
**Status:** [ ] TODO

---

## SECTION 8 — BACKTESTING & OPTIMIZATION [ MEDIUM PRIORITY ]

### 8.1 Firestore alert replay (backtester)
Use stored `alerts` collection data to replay historical signals.  
Since every bar since deployment is stored, we have real indicator history.

```bash
python -m agent.backtest --symbol BTCUSDT --from 2026-05-20 --to 2026-05-23
```

Output: trade-by-trade simulation with P&L, comparing rule configurations.

**File:** new `agent/backtest.py`  
**Status:** [ ] TODO

### 8.2 Signal threshold optimizer
Run backtest with different `bull_count` thresholds (3, 4, 5, 6) and compare:
- Win rate at each threshold
- Trade frequency vs profitability tradeoff
- Optimal TP/SL ratio per symbol

**Status:** [ ] TODO

### 8.3 Export trade log to CSV/Google Sheets
`python -m agent.export --format csv` → writes `trade_log.csv`  
Optional: auto-push to Google Sheets via Sheets API for easy analysis.

**Status:** [ ] TODO

---

## SECTION 9 — TELEGRAM/WHATSAPP/OPENCLAW CHAT INTERFACE [ HIGH PRIORITY ]

### 9.1 Telegram (Recommended — implement first)
**Why Telegram over WhatsApp:** Telegram has a proper Bot API (free, fast, no rate limits on personal bots). WhatsApp requires Meta Business API approval + paid tier.

**Setup steps:**
1. `pip install python-telegram-bot` (add to `agent/requirements.txt` + `pyproject.toml`)
2. Create bot via @BotFather in Telegram
3. Store `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` in GCP Secret Manager
4. Add `cloud/telegram.py` module with `send_message(text)` and command handler
5. Set Telegram webhook: `POST https://api.telegram.org/bot<TOKEN>/setWebhook?url=<CLOUD_RUN_URL>/telegram-webhook`

**File:** new `cloud/telegram.py`  
**Status:** [ ] TODO

### 9.2 OpenClaw / custom chat (future)
If you want a web chat UI instead of Telegram:
- Deploy a simple Next.js/React frontend on Vercel
- Backend: Cloud Run websocket endpoint
- Auth: Google OAuth (same GCP project)
- Real-time position updates via Firestore JS SDK
- Send trade commands from the UI

**Status:** [ ] FUTURE — do Telegram first

### 9.3 WhatsApp via Twilio (alternative)
If Telegram is blocked or not preferred:
- Use Twilio WhatsApp Sandbox → notifications only (no commands)
- Costs ~$0.05/message sent
- No incoming command support on free tier

**Status:** [ ] FUTURE — Telegram is better for this use case

---

## SECTION 10 — INDICATOR PINE SCRIPT UPDATES [ MEDIUM PRIORITY ]

### 10.1 Updated Pine Script with new indicators
Add to `tradingview/indicators.pine`:
```pine
// Stochastic RSI
[stochRsiK, stochRsiD] = ta.stoch(ta.rsi(close, 14), ta.rsi(close, 14), 14, 3)
smoothK = ta.sma(stochRsiK, 3)

// Bollinger Bands
[bbUpper, bbMid, bbLower] = ta.bb(close, 20, 2.0)
bbWidth = (bbUpper - bbLower) / bbMid

// ADX
[adxVal, diPlus, diMinus] = ta.dmi(14, 14)

// Export new fields in alert payload
plot(smoothK, "StochRSIK")
plot(bbWidth, "BBWidth") 
plot(adxVal, "ADX")
plot(diPlus, "DI_Plus")
```

**File:** `tradingview/indicators.pine`  
**Status:** [ ] TODO

### 10.2 Update cloud/main.py to store new fields
Add `stoch_rsi_k`, `bb_width`, `adx`, `di_plus` to the alert document stored in Firestore.

**File:** `cloud/main.py`  
**Status:** [ ] TODO

### 10.3 Update TradingView alert JSON template
Update `tradingview/SETUP.md` with the new payload fields.

**File:** `tradingview/SETUP.md`  
**Status:** [ ] TODO

---

## SECTION 11 — LIVE TRADING MIGRATION CHECKLIST [ FUTURE ]

Do this ONLY after testnet results are profitable over 2+ weeks.

- [ ] Review 14+ days of testnet trade log: win rate > 55%, avg R:R > 1.5
- [ ] Update `TRADING_MODE` in Secret Manager from `testnet` to `live`
- [ ] Fund Binance Futures account with real USDT
- [ ] Reduce position sizes to 50% for first week of live trading
- [ ] Set `MAX_DAILY_LOSS_USDT = 15` (conservative)
- [ ] Test with 1 trade manually before enabling AUTO_TRADE_ENABLED
- [ ] Monitor first 5 live trades closely via Telegram
- [ ] Gradually increase sizes if live results match testnet

---

## IMPLEMENTATION ORDER (RECOMMENDED)

```
Week 1 — Foundation
  [1.1] Fix permission prompts → .claude/settings.json
  [3.1] Create Telegram bot + store secrets  
  [3.2] Add trade notification messages
  [2.1] Add auto-executor to Cloud Run webhook (5/6 threshold)
  [7.5] Add /reconcile endpoint

Week 2 — Better Signals
  [4.1] Add StochRSI to Pine Script
  [4.3] Add ADX to Pine Script
  [4.6] MACD acceleration check in signals.py
  [4.5] Update to 8-point scoring
  [10.1-3] Update Pine Script + Cloud Run + SETUP.md

Week 3 — Risk & Money Management
  [5.1] Dynamic position sizing
  [5.2] Partial take profit
  [5.4] Daily loss limit
  [5.5] Correlation guard
  [5.8] Anti-whipsaw cooldown

Week 4 — Analytics & Reliability
  [6.1] Unrealized P&L in report
  [6.2] Trade performance stats
  [7.1] Cloud Run min-instances=1
  [7.2] Dead man's switch
  [7.3] Lot size precision lookup
  [8.1] Backtester using Firestore history

Week 5+ — Advanced Features
  [5.3] Trailing stop loss
  [3.3] Telegram command interface (/close, /pause, /resume)
  [3.4] Daily P&L Telegram summary
  [8.2] Signal threshold optimizer
```

---

## QUICK WINS (under 30 min each)

These can be done right now without a PC:

| Task | File | Time |
|------|------|------|
| Fix permission prompts | `.claude/settings.json` | 5 min |
| MACD acceleration check | `agent/signals.py:39` | 10 min |
| ATR-based dynamic sizing | `agent/signals.py:89-91` | 15 min |
| Anti-whipsaw cooldown state | `agent/config.py` | 10 min |
| Cloud Run min-instances in deploy | `.github/workflows/deploy.yml` | 5 min |
| Health check improvements | `cloud/main.py` | 15 min |
| Binance lot size precision | `agent/broker.py:43` | 20 min |

---

## NOTES ON ARCHITECTURE DECISION

**Why move execution to Cloud Run?**  
The current architecture requires your PC to be on AND Claude Code to be open AND you to confirm every trade. A 15-minute bar closes while you're asleep → signal fires → 30s poll detects it → Claude Code is closed → trade missed.

Moving execution to Cloud Run means:
- Webhook arrives → signal evaluated → trade placed in <5 seconds
- Works 24/7 without your laptop
- You get notified via Telegram after the fact
- You can still override via Telegram `/close` or `/pause`

**Risk:** Auto-execution means no human review. Mitigate by:
1. Starting with high threshold (5/6 signals, not 4/6)  
2. Small position sizes ($20-$25)  
3. Daily loss limit ($15-$20 max)  
4. Telegram alert on every auto-trade  
5. One-command pause: `/pause` via Telegram

---

*Generated from full codebase + GitHub history analysis. Reference commits: up to `9db4a13` (main branch as of 2026-05-23).*
