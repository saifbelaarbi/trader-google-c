# TradingBot

A production-ready TradingView webhook trading bot that receives signals from TradingView alerts, validates them against risk rules, and executes trades on Binance Futures via a Flask service hosted on Google Cloud Run. All position state is persisted in Firestore, enabling reconciliation after TP/SL hits without local memory.

## Architecture

```
TradingView Alert
      │
      │  POST /webhook  (X-Webhook-Secret header)
      ▼
┌─────────────────────────────┐
│      Google Cloud Run       │
│  Flask + Gunicorn (1w/1t)   │
│                             │
│  /webhook  → trade_engine   │
│  /reconcile → reconcile     │
│  /positions → state         │
│  /health                    │
└──────────┬──────────────────┘
           │                  │
           ▼                  ▼
   ┌──────────────┐   ┌──────────────────┐
   │   Firestore  │   │ Binance Futures   │
   │  (positions, │   │    Testnet /      │
   │  trade_log)  │   │    Live API       │
   └──────────────┘   └──────────────────┘
```

## TradingView Webhook Payload

```json
{
  "symbol":    "BTCUSDT",      // Trading pair, e.g. BTCUSDT
  "action":    "BUY",          // BUY | SELL | CLOSE
  "price":     65000.00,       // Entry price (current market price)
  "tp_pct":    1.0,            // Take-profit % distance from entry
  "sl_pct":    0.5,            // Stop-loss % distance from entry
  "size_usdt": 20.0,           // Position size in USDT (max 500)
  "timeframe": "5",            // Optional: chart timeframe
  "strategy":  "my_strategy"   // Optional: strategy name for logs
}
```

For `CLOSE` signals, only `symbol` and `action` are required.

## Local Development

```bash
# 1. Copy and fill in credentials
cp .env.example .env

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Run Flask dev server
flask --app app.main run

# 4. Test health endpoint
curl http://localhost:5000/health
```

For local runs without GCP, Firestore will fail on first use. Mock it or use the Firestore emulator.

## Testing

```bash
pytest tests/ -v
```

## GCP Setup

```bash
chmod +x scripts/setup_gcp.sh
./scripts/setup_gcp.sh <your-gcp-project-id>
```

This script:
- Enables all required GCP APIs
- Creates Firestore database (native mode, europe-west1)
- Creates Artifact Registry repo
- Creates a service account with least-privilege IAM roles
- Sets up Workload Identity Federation for GitHub Actions (no key files)
- Creates all 4 secrets in Secret Manager

## First Deploy

**Via Cloud Build (manual):**
```bash
gcloud builds submit --project=<project-id>
```

**Via GitHub Actions:** Push to `main` — CI runs tests then deploys automatically.

## GitHub Actions Secrets

| Secret | Description | Where to find |
|--------|-------------|---------------|
| `GCP_PROJECT_ID` | GCP project ID | Printed by `setup_gcp.sh` |
| `GCP_SA_EMAIL` | Service account email | Printed by `setup_gcp.sh` |
| `WORKLOAD_IDENTITY_PROVIDER` | WIF provider resource name | Printed by `setup_gcp.sh` |

Set these at: `GitHub repo → Settings → Secrets and variables → Actions`

## TradingView Configuration

1. Open TradingView and create or edit an alert on your strategy/indicator
2. In **Alert actions**, enable **Webhook URL**
3. Set the URL to: `https://<your-cloud-run-url>/webhook`
4. In the **Message** field, paste this template:
   ```json
   {
     "symbol": "{{ticker}}",
     "action": "{{strategy.order.action}}",
     "price": {{close}},
     "tp_pct": 1.0,
     "sl_pct": 0.5,
     "size_usdt": 20
   }
   ```
5. Add a custom header: `X-Webhook-Secret: <your WEBHOOK_SECRET value>`
   > TradingView supports custom headers under Alert → Advanced → Headers

## Switching to Live Trading

1. Update the `TRADING_MODE` secret in Secret Manager:
   ```bash
   echo -n "live" | gcloud secrets versions add TRADING_MODE --data-file=-
   ```
2. Update `BINANCE_API_KEY` and `BINANCE_API_SECRET` with your **live** Binance Futures API keys
3. Redeploy:
   ```bash
   gcloud builds submit --project=<project-id>
   ```
   or push to `main`.

> **Warning:** Always test with paper trading first. Use small `size_usdt` values initially.

## HTTP Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhook` | Receive TradingView signal; requires `X-Webhook-Secret` header |
| `GET` | `/health` | Liveness check; returns `{"status":"ok","mode":"testnet"}` |
| `GET` | `/reconcile` | Sync Firestore positions against live Binance state |
| `GET` | `/positions` | List all currently open positions from Firestore |
