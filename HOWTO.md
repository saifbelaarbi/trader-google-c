# TradingBot — Quick Setup & Paper Trading Guide

Everything you need to go from zero to live paper-trading signals hitting Binance testnet. Read top-to-bottom, run each block, move on.

---

## Prerequisites

| Tool | Install |
|------|---------|
| `gcloud` CLI | https://cloud.google.com/sdk/docs/install |
| `docker` | https://docs.docker.com/get-docker/ |
| Python 3.12 | https://python.org/downloads (or `pyenv install 3.12`) |
| A Google account | — |
| A TradingView account (free works) | — |

---

## Step 1 — Create a GCP Project

```bash
# Log in
gcloud auth login

# Create a new project (or skip if you have one)
gcloud projects create tradingbot-prod --name="TradingBot"

# Set it as default
gcloud config set project tradingbot-prod

# Link billing (required for Cloud Run + Secret Manager)
# → https://console.cloud.google.com/billing → link your project
```

---

## Step 2 — Get Binance Testnet API Keys

1. Go to **https://testnet.binancefuture.com**
2. Click **Sign In** (create account if needed — testnet uses its own login)
3. Click your avatar → **API Management** → **Create API**
4. Copy both `API Key` and `Secret Key` — you'll need them in Step 4

> Testnet starts you with 10,000 USDT. No real money involved.

---

## Step 3 — Clone the Repo & Generate a Webhook Secret

```bash
git clone https://github.com/saifbelaarbi/trader-google-c.git
cd trader-google-c

# Generate a strong random webhook secret
python3 -c "import secrets; print(secrets.token_hex(32))"
# → copy the output, e.g. a3f8c2d1e4b5...
```

Keep this value — you'll use it in Step 4 AND in TradingView.

---

## Step 4 — Run the GCP Setup Script

This single script provisions everything: APIs, Firestore, Artifact Registry, service account, Workload Identity, and all secrets.

```bash
chmod +x scripts/setup_gcp.sh
./scripts/setup_gcp.sh tradingbot-prod
```

When prompted, paste:
- **BINANCE_API_KEY** → your testnet API key from Step 2
- **BINANCE_API_SECRET** → your testnet secret key from Step 2
- **WEBHOOK_SECRET** → the hex string from Step 3

`TRADING_MODE` is set to `testnet` automatically by the script.

At the end the script prints three values — **copy them now**:
```
GCP_PROJECT_ID=tradingbot-prod
GCP_SA_EMAIL=tradingbot-sa@tradingbot-prod.iam.gserviceaccount.com
WORKLOAD_IDENTITY_PROVIDER=projects/123.../providers/github-provider
```

---

## Step 5 — Add GitHub Actions Secrets

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|------|-------|
| `GCP_PROJECT_ID` | `tradingbot-prod` |
| `GCP_SA_EMAIL` | printed by setup script |
| `WORKLOAD_IDENTITY_PROVIDER` | printed by setup script |

---

## Step 6 — First Deploy

Push to `main` — GitHub Actions runs tests then deploys automatically:

```bash
git push origin main
```

Watch it at: **https://github.com/saifbelaarbi/trader-google-c/actions**

Or deploy manually without GitHub Actions:

```bash
# Build and deploy in one command
IMAGE="europe-west1-docker.pkg.dev/tradingbot-prod/tradingbot/app:manual"

gcloud auth configure-docker europe-west1-docker.pkg.dev
docker build -t "$IMAGE" .
docker push "$IMAGE"

gcloud run deploy tradingbot \
  --image="$IMAGE" \
  --region=europe-west1 \
  --service-account=tradingbot-sa@tradingbot-prod.iam.gserviceaccount.com \
  --min-instances=1 \
  --max-instances=3 \
  --memory=256Mi \
  --cpu=1 \
  --timeout=30 \
  --concurrency=1 \
  --allow-unauthenticated \
  --set-secrets="BINANCE_API_KEY=BINANCE_API_KEY:latest,BINANCE_API_SECRET=BINANCE_API_SECRET:latest,WEBHOOK_SECRET=WEBHOOK_SECRET:latest,TRADING_MODE=TRADING_MODE:latest"
```

---

## Step 7 — Get Your Service URL & Verify

```bash
# Get the deployed URL
gcloud run services describe tradingbot \
  --region=europe-west1 \
  --format="value(status.url)"
# → https://tradingbot-xxxx-ew.a.run.app
```

```bash
# Verify health
curl https://tradingbot-xxxx-ew.a.run.app/health
# → {"mode": "testnet", "status": "ok"}
```

---

## Step 8 — Configure TradingView

### 8a. Set up the Webhook Alert

1. Open a chart on TradingView
2. Add your strategy or indicator (or use any built-in one to test)
3. Click the **Alerts** clock icon → **Create Alert**
4. Set your **Condition** (e.g. strategy fires, crossover, etc.)
5. In **Alert actions**: tick **Webhook URL**
6. Paste your Cloud Run URL + `/webhook`:
   ```
   https://tradingbot-xxxx-ew.a.run.app/webhook
   ```

### 8b. Set the Message Body

Paste this in the **Message** field:

```json
{
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "price": {{close}},
  "tp_pct": 1.0,
  "sl_pct": 0.5,
  "size_usdt": 20,
  "timeframe": "{{interval}}",
  "strategy": "{{strategy.order.comment}}"
}
```

> For manual alerts (not Pine Script strategies), hard-code the action: `"action": "BUY"`

### 8c. Add the Auth Header

In the alert dialog → **Advanced** → **Additional Headers**:

```
X-Webhook-Secret: a3f8c2d1e4b5...   ← your WEBHOOK_SECRET from Step 3
```

---

## Step 9 — Test It Manually

Before waiting for TradingView, fire a test signal yourself:

```bash
export WEBHOOK_SECRET="a3f8c2d1e4b5..."  # your secret

./scripts/trigger_test_webhook.sh https://tradingbot-xxxx-ew.a.run.app BUY
```

Expected response:
```json
{
  "entry": 65000.0,
  "qty": 0.000308,
  "side": "BUY",
  "sl": 64675.0,
  "status": "opened",
  "symbol": "BTCUSDT",
  "tp": 65650.0
}
```

Verify the order appeared on Binance testnet:
→ **https://testnet.binancefuture.com** → Orders → Open Orders

Check the position is recorded in Firestore:
```bash
curl https://tradingbot-xxxx-ew.a.run.app/positions
# → [{"side": "BUY", "entry_price": 65000.0, ...}]
```

Send a CLOSE to clean up:
```bash
./scripts/trigger_test_webhook.sh https://tradingbot-xxxx-ew.a.run.app CLOSE
```

---

## Step 10 — Set Up Reconciliation (Cron)

When a TP or SL hits on Binance, the bot doesn't receive a callback. Run reconciliation on a schedule to keep Firestore in sync.

**Option A — Cloud Scheduler (recommended)**

```bash
# Enable the API
gcloud services enable cloudscheduler.googleapis.com

# Create a job that calls /reconcile every 5 minutes
gcloud scheduler jobs create http tradingbot-reconcile \
  --location=europe-west1 \
  --schedule="*/5 * * * *" \
  --uri="https://tradingbot-xxxx-ew.a.run.app/reconcile" \
  --http-method=GET \
  --time-zone="UTC"
```

**Option B — Cron on a VM**

```bash
# Add to crontab: crontab -e
*/5 * * * * curl -s https://tradingbot-xxxx-ew.a.run.app/reconcile > /dev/null
```

---

## Day-to-Day Operations

### View open positions
```bash
curl https://tradingbot-xxxx-ew.a.run.app/positions
```

### View live logs
```bash
gcloud logging read 'resource.type="cloud_run_revision" resource.labels.service_name="tradingbot"' \
  --limit=50 \
  --format="value(jsonPayload.message)" \
  --project=tradingbot-prod
```

### Trigger reconciliation manually
```bash
curl https://tradingbot-xxxx-ew.a.run.app/reconcile
```

### Check Firestore data directly
→ https://console.cloud.google.com/firestore → `positions` collection

---

## Risk Settings (before going live)

Edit `app/risk.py` to match your strategy:

```python
MAX_SIZE_USDT = 20.0      # max $ per trade (start small)
MAX_SL_PCT    = 1.0       # tighten stop-loss cap
MIN_TP_SL_RATIO = 1.5     # require better R:R
ALLOWED_SYMBOLS = ["BTCUSDT", "ETHUSDT"]  # whitelist symbols
```

After editing, commit and push → auto-redeploy.

---

## Switching to Live Trading (when ready)

1. Get **live** Binance Futures API keys from https://www.binance.com → API Management
2. Update the secrets:
   ```bash
   echo -n "your_live_api_key" | gcloud secrets versions add BINANCE_API_KEY --data-file=-
   echo -n "your_live_secret"  | gcloud secrets versions add BINANCE_API_SECRET --data-file=-
   echo -n "live"              | gcloud secrets versions add TRADING_MODE --data-file=-
   ```
3. Redeploy:
   ```bash
   git commit --allow-empty -m "switch to live" && git push origin main
   ```
4. Verify: `curl .../health` → `{"mode": "live", ...}`

> Start with `MAX_SIZE_USDT = 20` on live until you've verified everything works.

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `/health` returns 503 | Cloud Run not deployed; check Actions tab |
| 401 on webhook | Wrong `X-Webhook-Secret` header value |
| 400 "size_usdt exceeds MAX_SIZE_USDT" | Payload `size_usdt` > 500 |
| 400 "Calculated qty is 0" | `size_usdt` too small for `price`; increase it |
| Order rejected by Binance | Check testnet.binancefuture.com for error; usually wrong symbol or qty precision |
| Position stuck in Firestore after TP/SL | Run `/reconcile` — it will clear ghost positions |
| Logs show "WEBHOOK_SECRET is not configured" | Secret not mounted; check `--set-secrets` in deploy command |
