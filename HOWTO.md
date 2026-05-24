# TradingBot — Setup & Operations Guide

**Current stack:** TradingView → Cloud Run (relay) → Firestore → Claude Code (brain) → Bybit testnet
**Last updated:** 2026-05-24

---

## Architecture

```
TradingView
  └── POST /webhook (bar-close alerts, every 15m + 1h)
         │
         ▼
  Cloud Run (tradingbot-grpyjoqoaq-ew.a.run.app)
    · Validates secret · Stores alert in Firestore · Sends Telegram signal ping
    · Auto-trade thread (OFF by default — Claude is the trader)
         │
         ├── Firestore (tradingbot-496815)
         │     alerts / positions / trade_log / decisions
         │
         └── Telegram (saif_trader_bot)
               · Trade notifications · /status /positions /close /pause /resume

Claude Code (you, the trading brain)
  └── python -m agent.report         → read live indicators
  └── python -m agent.executor open  → place trade
  └── python -m agent.executor close → close trade
         │
         ▼
  Bybit testnet (USDT perpetuals)
    · Supports longs + shorts · Native TP/SL · $200 budget
```

**Claude is the only trading brain.** Cloud Run is a relay, not an auto-trader.
The auto-execute thread in Cloud Run exists but is OFF by default. Only enable it
(`/resume` in Telegram) if you want fully autonomous rule-based trading.

---

## GCP Infrastructure (already provisioned — do not re-create)

| Resource | Value |
|----------|-------|
| GCP project | `tradingbot-496815` |
| Region | `europe-west1` |
| Cloud Run URL | `https://tradingbot-grpyjoqoaq-ew.a.run.app` |
| Firestore DB | `(default)` native mode |
| Artifact Registry | `europe-west1-docker.pkg.dev/tradingbot-496815/tradingbot/` |
| Service account | `tradingbot-sa@tradingbot-496815.iam.gserviceaccount.com` |
| SA key file | `sa-key.json` (in repo root, auto-loaded by setup-session.sh) |

### Secrets in Secret Manager

| Secret | Purpose |
|--------|---------|
| `BYBIT_API_KEY` | Bybit testnet API key |
| `BYBIT_API_SECRET` | Bybit testnet secret |
| `WEBHOOK_SECRET` | TradingView webhook auth (`changeme123`) |
| `TELEGRAM_BOT_TOKEN` | Bot token |
| `TELEGRAM_CHAT_ID` | Your chat ID |
| `TRADING_MODE` | `testnet` or `live` |
| `AUTO_TRADE_ENABLED` | `false` (Claude trades manually) |
| `AUTO_TRADE_MIN_SIGNALS` | `5` |

---

## Starting a Claude Code session

Session setup runs automatically (`.claude/setup-session.sh`):
1. Loads SA key from `sa-key.json` → `/tmp/gcp-sa-key.json`
2. Writes `agent/.env` with all credentials
3. Installs Python dependencies
4. Sends Telegram ping: "Claude trading session started"

**Default credentials (testnet):**
```
BYBIT_API_KEY     = x28DIhmPtaPyoNhGG1
BYBIT_API_SECRET  = 0HLHaLi5Axnlsvr3eAae8S7LWb4UAKGL9h3z
TRADING_MODE      = testnet
```

After session starts, run:
```bash
python -m agent.report
```

This shows open positions, last 8h of 15m + 1h indicators, and signal scores for
BTCUSDT, ETHUSDT, SOLUSDT.

---

## Day-to-day trading workflow

### 1. Read state
```bash
python -m agent.report                # all symbols
python -m agent.report BTCUSDT       # single symbol
python -m agent.executor positions   # just open positions
```

### 2. Analyze (Claude does this)
- EMA20 vs EMA50 on 15m AND 1h must agree on trend direction
- RSI14: bull zone 50–72, bear zone 28–50
- MACD histogram: positive AND growing (acceleration, not just positive)
- Vol ratio: > 1.3 = high conviction, < 0.8 = skip
- EMA slope: EMA20 trending in signal direction for last 2+ bars
- Score: require ≥ 4/6 indicators before trading (TESTNET), ≥ 5/6 (LIVE)

### 3. Execute
```bash
# Open long
python -m agent.executor open --symbol BTCUSDT --side BUY --size 25 --tp 1.5 --sl 0.8

# Open short
python -m agent.executor open --symbol ETHUSDT --side SELL --size 20 --tp 1.2 --sl 0.7

# Close
python -m agent.executor close --symbol BTCUSDT
```

Telegram notifies you automatically after execution.

### Risk limits

| Rule | TESTNET | LIVE |
|------|---------|------|
| Max size per trade | $40 | $25 |
| Preferred size | $20–30 | $15–20 |
| Min signal score | 4/6 | 5/6 |
| Max stop-loss | 3% | 2% |
| Min TP/SL ratio | 1.5 | 1.8 |
| RSI overbought (no longs) | 75 | 70 |
| RSI oversold (no shorts) | 25 | 30 |
| Max concurrent positions | 2 | 2 |

---

## Telegram bot commands

Send from Telegram to `saif_trader_bot`:

| Command | Action |
|---------|--------|
| `/status` | Mode, auto-trade on/off, open positions count |
| `/positions` | All open positions with entry/TP/SL |
| `/close BTCUSDT` | Close a position immediately |
| `/pause` | Disable auto-trading (Cloud Run thread) |
| `/resume` | Enable auto-trading |
| `/help` | Command list |

---

## Cloud Run endpoints

Base URL: `https://tradingbot-grpyjoqoaq-ew.a.run.app`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Status: mode, auto_trade, min_signals |
| POST | `/webhook` | TradingView alert ingestion (needs X-Webhook-Secret header) |
| GET | `/state` | All positions + last 32 bars per symbol (for Claude) |
| GET | `/indicators/BTCUSDT` | Per-symbol indicator history (`?n=32&tf=15`) |
| GET | `/reconcile` | Clear Firestore ghost positions vs Bybit reality |
| GET | `/positions` | Open positions list |
| POST | `/telegram-webhook` | Telegram bot command handler |

```bash
# Quick health check
curl https://tradingbot-grpyjoqoaq-ew.a.run.app/health

# Read full state (positions + indicators)
curl https://tradingbot-grpyjoqoaq-ew.a.run.app/state | python3 -m json.tool

# Manual reconcile
curl https://tradingbot-grpyjoqoaq-ew.a.run.app/reconcile
```

---

## TradingView alert configuration

### Webhook URL
```
https://tradingbot-grpyjoqoaq-ew.a.run.app/webhook
```

### Required header
```
X-Webhook-Secret: changeme123
```

### Alert message body (JSON)
```json
{
  "symbol": "{{ticker}}",
  "timeframe": "{{interval}}",
  "price":     {{close}},
  "ema20":     {{plot_0}},
  "ema50":     {{plot_1}},
  "rsi14":     {{plot_2}},
  "macd_hist": {{plot_3}},
  "atr14":     {{plot_4}},
  "vol_ratio": {{plot_5}}
}
```

Set up one alert per symbol per timeframe (15m and 1h each).
`plot_0` through `plot_5` correspond to your indicator outputs — map them in TradingView.
See `tradingview/SETUP.md` for the full Pine Script.

---

## Deployment (CI/CD)

Every push to `main` triggers GitHub Actions:
1. `ruff check cloud/ tests/` — lint
2. `pytest tests/ -v` — unit tests
3. Docker build + push to Artifact Registry
4. `gcloud run deploy` with all secrets from Secret Manager

Manual deploy:
```bash
git push origin main
```

Watch CI: `https://github.com/saifbelaarbi/trader-google-c/actions`

---

## GCP operations (Cloud Shell)

```bash
# View live Cloud Run logs
gcloud logging read \
  'resource.type="cloud_run_revision" resource.labels.service_name="tradingbot"' \
  --limit=50 --format="value(jsonPayload.message)" \
  --project=tradingbot-496815

# Update a secret
echo -n "new_value" | gcloud secrets versions add SECRET_NAME \
  --data-file=- --project=tradingbot-496815

# Deploy latest image manually
gcloud run services update tradingbot --region=europe-west1 \
  --project=tradingbot-496815

# Set up reconcile cron (run once)
gcloud scheduler jobs create http tradingbot-reconcile \
  --location=europe-west1 \
  --schedule="*/5 * * * *" \
  --uri="https://tradingbot-grpyjoqoaq-ew.a.run.app/reconcile" \
  --http-method=GET --time-zone="UTC" \
  --project=tradingbot-496815
```

---

## Switching to live trading

Only when testnet is profitable for 14+ days.

1. Get live Bybit API keys from https://bybit.com → API Management
2. Update secrets:
   ```bash
   echo -n "live_api_key" | gcloud secrets versions add BYBIT_API_KEY --data-file=- --project=tradingbot-496815
   echo -n "live_secret"  | gcloud secrets versions add BYBIT_API_SECRET --data-file=- --project=tradingbot-496815
   echo -n "live"         | gcloud secrets versions add TRADING_MODE --data-file=- --project=tradingbot-496815
   ```
3. Push to main → redeploy.
4. Verify: `curl .../health` → `{"mode": "live", ...}`
5. Start with half position sizes. Monitor first 5 trades via Telegram.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `agent/report.py` shows "(no data)" for all symbols | TradingView alerts not firing. Check Pine Script is published and alerts are active. |
| `/health` returns 503 | Cloud Run not deployed. Check GitHub Actions. |
| 401 on webhook | Wrong `X-Webhook-Secret`. Check TradingView alert header matches secret. |
| Position stuck in Firestore after TP/SL hit | Run `/reconcile` manually. Then set up Cloud Scheduler cron (H1 in TODO). |
| `executor open` returns "No alert data" | No 15m bar received yet for that symbol. Wait for TradingView bar close. |
| Telegram "notification failed (network restricted)" | Expected in Claude Code container. Cloud Run sends Telegram fine. |
| `CERTIFICATE_VERIFY_FAILED` on Firestore | gRPC is blocked. `agent/state.py` uses REST API — should not happen. |
| Bybit order rejected | Check qty precision. BTC needs 3dp, ETH 2dp, SOL 1dp. See TODO M5. |
