# TradingBot — Session Handoff

**Last updated:** 2026-05-24
**Status:** Fully operational on testnet. Claude is the trading brain.

---

## What is already working (do not re-create)

### Infrastructure

| Resource | Status | Value |
|----------|--------|-------|
| GCP project | ✅ | `tradingbot-496815` |
| Cloud Run | ✅ live | `https://tradingbot-grpyjoqoaq-ew.a.run.app` |
| Firestore | ✅ | `(default)`, europe-west1. Collections: alerts / positions / trade_log |
| Artifact Registry | ✅ | `europe-west1-docker.pkg.dev/tradingbot-496815/tradingbot/` |
| Service account | ✅ | `tradingbot-sa@tradingbot-496815.iam.gserviceaccount.com` |
| SA key | ✅ | `sa-key.json` in repo root — auto-loaded by setup-session.sh |
| All 8 secrets | ✅ | Secret Manager: BYBIT_API_KEY, BYBIT_API_SECRET, WEBHOOK_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TRADING_MODE, AUTO_TRADE_ENABLED, AUTO_TRADE_MIN_SIGNALS |
| CI/CD | ✅ | GitHub Actions → test → build → Cloud Run deploy on push to main |

### Code

| Component | Status | File |
|-----------|--------|------|
| Cloud Run relay (webhook → Firestore → Telegram) | ✅ | `cloud/main.py` |
| Firestore REST API layer | ✅ | `agent/state.py` (gRPC blocked, uses HTTPS) |
| Bybit broker (longs + shorts + native TP/SL) | ✅ | `agent/brokers/bybit.py` |
| Signal engine (6-point, MACD accel, EMA slope) | ✅ | `agent/signals.py` |
| Risk gate | ✅ | `agent/risk.py` |
| `agent/report.py` — live state report | ✅ | `python -m agent.report` |
| `agent/executor.py` — Claude's trade tool | ✅ | `python -m agent.executor open/close/positions` |
| Telegram bot commands (/status /positions /close /pause /resume /help) | ✅ | `cloud/main.py` telegram-webhook handler |
| Session auto-start + Telegram ping | ✅ | `.claude/setup-session.sh` |
| Auto-execute thread (off by default) | ✅ | `cloud/main.py` `_evaluate_and_trade()` |

---

## System architecture

```
TradingView alerts (bar close, 15m + 1h)
  └── POST /webhook
        │
        ▼
  Cloud Run relay
    · Stores alert in Firestore
    · Sends Telegram signal ping
    · Auto-trade thread (OFF — Claude is the trader)
        │
        ├── Firestore  ◄── Claude reads this via agent/state.py (REST)
        └── Telegram   ◄── Notifications + commands from user

Claude Code (the trading brain)
  └── python -m agent.report         → read live indicators + signals
  └── python -m agent.executor open  → place trade on Bybit
  └── python -m agent.executor close → close trade
        │
        ▼
  Bybit testnet
    USDT perpetuals · supports shorts · native TP/SL · $200 budget
```

**Important:** Claude makes all trading decisions. The Cloud Run auto-trade thread is OFF by default.
The Telegram bot reports back to the user — Claude does NOT interact with Telegram directly.

---

## Starting a new Claude Code session

Session setup runs automatically. Confirm at the top of any new session:
```
TRADING_MODE : TESTNET
GCP CREDS    : present
BYBIT KEYS   : present (testnet)
```

If GCP CREDS shows MISSING, paste the SA key:
```bash
echo "BASE64_KEY" | base64 -d > /tmp/gcp-sa-key.json
export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-sa-key.json
```

First command every session:
```bash
python -m agent.report
```

---

## Trading workflow (every session)

1. **Read state:** `python -m agent.report`
2. **Analyze** indicators (EMA trend, RSI zone, MACD acceleration, vol ratio, EMA slope)
3. **Recommend** with reasoning. No signal = WAIT (safe default).
4. **Execute** after confirming with user:
   ```bash
   python -m agent.executor open --symbol BTCUSDT --side BUY --size 25 --tp 1.5 --sl 0.8
   python -m agent.executor close --symbol ETHUSDT
   ```
5. Telegram notifies user automatically.

---

## Key credentials (testnet)

```
BYBIT_API_KEY     = x28DIhmPtaPyoNhGG1
BYBIT_API_SECRET  = 0HLHaLi5Axnlsvr3eAae8S7LWb4UAKGL9h3z
TRADING_MODE      = testnet
TELEGRAM_TOKEN    = 8637585030:AAGNJ8Zj0JemJxKz5MzBYTteWTknsc5lCfA
TELEGRAM_CHAT_ID  = 8293278264
CLOUD_RUN_URL     = https://tradingbot-grpyjoqoaq-ew.a.run.app
WEBHOOK_SECRET    = changeme123
```

---

## Next priorities (from TODO.md)

1. **[H1]** Set up Cloud Scheduler reconcile cron every 5 min (prevents ghost positions after TP/SL)
2. **[H2]** Add daily loss limit ($20 auto-pause in `_evaluate_and_trade()`)
3. **[M5]** Fix Bybit qty precision per symbol (currently hardcoded `round(qty, 3)`)
4. **[H3]** Show unrealized P&L in `agent/report.py`

Full list: see `TODO.md`.

---

## Useful quick commands

```bash
# Full state report
python -m agent.report

# Just positions
python -m agent.executor positions

# Open a trade (Claude confirms first, then runs this)
python -m agent.executor open --symbol BTCUSDT --side BUY --size 25 --tp 1.5 --sl 0.8

# Cloud Run health
curl https://tradingbot-grpyjoqoaq-ew.a.run.app/health

# Cloud Run full state (positions + bars)
curl https://tradingbot-grpyjoqoaq-ew.a.run.app/state | python3 -m json.tool

# Manual reconcile (clear ghost positions)
curl https://tradingbot-grpyjoqoaq-ew.a.run.app/reconcile

# GCP logs
gcloud logging read \
  'resource.type="cloud_run_revision" resource.labels.service_name="tradingbot"' \
  --limit=30 --format="value(jsonPayload.message)" \
  --project=tradingbot-496815
```

---

## Opening prompt for a new Claude Code session

Paste this at the start of each session:

---

> **TradingBot session — TESTNET**
>
> Read `CLAUDE.md` before doing anything. You are the trading brain for this bot.
>
> Session is already configured (setup-session.sh ran automatically). Credentials are present.
>
> **Start by running:** `python -m agent.report`
>
> Then analyze the indicators and tell me:
> 1. What the current market context is for BTCUSDT, ETHUSDT, SOLUSDT
> 2. Whether any symbol has ≥ 4/6 signals aligned for a trade
> 3. What you recommend and why
>
> Do not execute any trade without confirming with me first.
>
> **Mode: TESTNET** — paper money only.
> Budget: $200 testnet USDT. Max $30 per trade. Max 2 concurrent positions.
>
> GCP project: `tradingbot-496815` | Cloud Run: `https://tradingbot-grpyjoqoaq-ew.a.run.app`
