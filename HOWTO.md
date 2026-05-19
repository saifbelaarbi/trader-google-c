# TradingBot — Deployment & Setup Guide

Two-part system:
1. **Cloud Run relay** (always running on GCP) — receives TradingView webhooks, stores alerts in Firestore
2. **Local agent** (runs on your PC when you open a Claude Code session) — reads Firestore, analyzes signals, executes trades on Binance testnet

---

## Part 1 — GCP Setup (one time)

### Step 1 — Create a GCP project

In [Google Cloud Console](https://console.cloud.google.com):

1. Click the project selector → **New Project**
2. Give it a name (e.g. `tradingbot`) — GCP will assign an ID like `tradingbot-123456`
3. Note the **Project ID** (not the name) — you'll use it everywhere

Or via Cloud Shell:
```bash
gcloud projects create tradingbot-YOURNAME --name="TradingBot"
gcloud config set project tradingbot-YOURNAME
```

Link billing: [console.cloud.google.com/billing](https://console.cloud.google.com/billing) → link your project.

---

### Step 2 — Run the GCP setup script

```bash
# In Cloud Shell (or local gcloud)
cd trader-google-c
chmod +x scripts/setup_gcp.sh
./scripts/setup_gcp.sh YOUR_PROJECT_ID
```

When prompted, paste:
- **BINANCE_API_KEY** — from https://testnet.binancefuture.com → API Management
- **BINANCE_API_SECRET** — same
- **WEBHOOK_SECRET** — generate with: `python3 -c "import secrets; print(secrets.token_hex(32))"`

At the end the script prints three values — copy them:
```
GCP_PROJECT_ID=tradingbot-YOURNAME
GCP_SA_EMAIL=tradingbot-sa@tradingbot-YOURNAME.iam.gserviceaccount.com
WORKLOAD_IDENTITY_PROVIDER=projects/123.../providers/github-provider
```

---

### Step 3 — Create Firestore composite index

The agent queries alerts by (symbol, timeframe, received_at). You need to create this index once.

```bash
gcloud firestore indexes composite create \
  --project=YOUR_PROJECT_ID \
  --collection-group=alerts \
  --field-config field-path=symbol,order=ascending \
  --field-config field-path=timeframe,order=ascending \
  --field-config field-path=received_at,order=descending
```

Or deploy it from the file in the repo:
```bash
gcloud firestore indexes composite list --project=YOUR_PROJECT_ID
# If empty, create via console: Firestore → Indexes → Add composite index
# Collection: alerts  Fields: symbol ASC, timeframe ASC, received_at DESC
```

---

### Step 4 — Add GitHub Actions secrets

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|------|-------|
| `GCP_PROJECT_ID` | your project ID |
| `GCP_SA_EMAIL` | printed by setup script |
| `WORKLOAD_IDENTITY_PROVIDER` | printed by setup script |

---

### Step 5 — First deploy

Push to `main` — GitHub Actions will test and deploy automatically:

```bash
git push origin main
```

Watch it at: `github.com/YOUR_USERNAME/trader-google-c/actions`

Once green, get your Cloud Run URL:
```bash
gcloud run services describe tradingbot \
  --region=europe-west1 \
  --project=YOUR_PROJECT_ID \
  --format="value(status.url)"
# → https://tradingbot-xxxx-ew.a.run.app
```

Verify:
```bash
curl https://tradingbot-xxxx-ew.a.run.app/health
# → {"role": "relay", "status": "ok"}
```

---

## Part 2 — TradingView Setup

See `tradingview/SETUP.md` for detailed instructions.

Summary:
1. Add `tradingview/indicators.pine` to each of your 6 charts (BTCUSDT/ETHUSDT/SOLUSDT × 15m/1h)
2. Create one "Bar Close" alert per chart
3. Set webhook URL to `https://YOUR_CLOUD_RUN_URL/webhook`
4. Paste `tradingview/webhook_template.json` as the message body
5. Add header `X-Webhook-Secret: YOUR_WEBHOOK_SECRET`

After the first bar closes, check Firestore → `alerts` collection to confirm data is flowing.

---

## Part 3 — Local Agent Setup (your PC)

### Install dependencies

```bash
cd trader-google-c
pip install -r agent/requirements.txt
```

### Set up environment

Create `agent/.env` from the example:
```bash
cp .env.example agent/.env
# Edit agent/.env and fill in:
#   ANTHROPIC_API_KEY  ← not needed (we use Claude Code instead)
#   BINANCE_API_KEY    ← your testnet key
#   BINANCE_API_SECRET ← your testnet secret
#   TRADING_MODE=testnet
```

### GCP credentials for local Firestore access

**Option A** (recommended): Download a service account key

```bash
gcloud iam service-accounts keys create ~/tradingbot-sa-key.json \
  --iam-account=tradingbot-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --project=YOUR_PROJECT_ID
```

Then add to `agent/.env`:
```
GOOGLE_APPLICATION_CREDENTIALS=/home/youruser/tradingbot-sa-key.json
```

**Option B**: Use application default credentials (simpler, no key file)
```bash
gcloud auth application-default login
# No env var needed after this
```

---

## Part 4 — Trading Sessions

### How trading works

You don't run a separate AI process. **Claude Code (this CLI) is the agent.**

1. Open a Claude Code session in the repo directory
2. Say "check my trading bot" or "run a trading session"
3. I run `python -m agent.report` to read the current state from Firestore
4. I analyze the 8-hour indicator history and give you a recommendation
5. You confirm → I execute via `python -m agent.executor`

### Optional background monitor

If you want signals detected and saved to Firestore even when you're not in a session:

```bash
python -m agent.main
```

This runs the rule-based signal engine in the background. It saves detected signals to Firestore `signals` collection but **never executes trades** — that only happens in a Claude Code session.

### Run a manual session check

```bash
python -m agent.report              # all symbols
python -m agent.report BTCUSDT      # single symbol
```

---

## Useful commands

```bash
# View open positions
python -m agent.executor positions

# Execute a trade (Claude Code calls this)
python -m agent.executor open --symbol BTCUSDT --side BUY --size 25 --tp 1.2 --sl 0.7

# Close a position
python -m agent.executor close --symbol BTCUSDT

# View Cloud Run logs
gcloud logging read \
  'resource.type="cloud_run_revision" resource.labels.service_name="tradingbot"' \
  --limit=30 --project=YOUR_PROJECT_ID

# Check Firestore alerts are flowing
# → GCP Console → Firestore → alerts collection
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `/health` returns 503 | Cloud Run not deployed — check GitHub Actions tab |
| 401 on webhook | Wrong `X-Webhook-Secret` in TradingView alert |
| `alerts` collection empty after first bar | Check Cloud Run logs; verify TradingView alert is active and using correct URL |
| Firestore query error (index missing) | Create composite index — see Step 3 above |
| `agent/report.py` shows no data | Alerts not flowing yet — wait for TradingView bar close |
| Binance order rejected | Check testnet.binancefuture.com for error; usually symbol or qty precision |

---

## Switching to live trading (when ready)

1. Get **live** Binance Futures API keys from https://www.binance.com → API Management
2. Update secrets in GCP Secret Manager:
   ```bash
   echo -n "your_live_api_key" | gcloud secrets versions add BINANCE_API_KEY --data-file=- --project=YOUR_PROJECT_ID
   echo -n "your_live_secret"  | gcloud secrets versions add BINANCE_API_SECRET --data-file=- --project=YOUR_PROJECT_ID
   ```
3. Update `agent/.env` on your PC with the live keys and `TRADING_MODE=live`
4. Start with `MAX_SIZE_USDT = 20` in `agent/config.py`
