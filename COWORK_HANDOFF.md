# TradingBot — Cowork Handoff

**Session goal:** Pick up where setup left off, choose a paper-trading strategy, wire up TradingView, run a first live test with the $200 testnet budget, and identify upgrades.

---

## 1. What is already done (do not redo)

### GCP — project `strader-496414`

| Resource | Status | Value |
|----------|--------|-------|
| GCP project | ✅ exists | `strader-496414` |
| Firestore (native) | ✅ created | `europe-west1` |
| Artifact Registry | ✅ created | `europe-west1-docker.pkg.dev/strader-496414/tradingbot/` |
| Service account | ✅ created + IAM roles bound | `tradingbot-sa@strader-496414.iam.gserviceaccount.com` |
| Workload Identity Pool | ✅ created | `github-pool` (global) |
| WIF Provider | ✅ created | `github-provider`, bound to `saifbelaarbi/trader-google-c` |
| Secrets | ✅ in Secret Manager | `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `WEBHOOK_SECRET`, `TRADING_MODE=testnet` |

### GitHub repo `saifbelaarbi/trader-google-c`

| Item | Status |
|------|--------|
| Full bot code on `main` | ✅ |
| GitHub Actions workflow (`.github/workflows/deploy.yml`) | ✅ |
| GitHub Actions secrets | ⏳ **still needed** — see Section 2 |

### Cloud Run

| Item | Status |
|------|--------|
| First deploy | ⏳ **not yet** — happens automatically after GitHub secrets are added and a push to `main` |

---

## 2. First thing to do — add GitHub Actions secrets

Navigate to: `github.com/saifbelaarbi/trader-google-c` → **Settings** tab (top of page) → left sidebar → **Secrets and variables** → **Actions** → **New repository secret**

Add all three:

| Secret name | Value |
|-------------|-------|
| `GCP_PROJECT_ID` | `strader-496414` |
| `GCP_SA_EMAIL` | `tradingbot-sa@strader-496414.iam.gserviceaccount.com` |
| `WORKLOAD_IDENTITY_PROVIDER` | run command below in Cloud Shell to get it |

```bash
gcloud iam workload-identity-pools providers describe "github-provider" \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --project="strader-496414" \
  --format="value(name)"
```

Once all three secrets are added → trigger first deploy:

```bash
# In Cloud Shell or local terminal
git clone https://github.com/saifbelaarbi/trader-google-c.git
cd trader-google-c
git commit --allow-empty -m "trigger first deploy" && git push origin main
```

Watch CI: `github.com/saifbelaarbi/trader-google-c/actions`

---

## 3. Trading setup context

### Broker & mode
- **Exchange:** Binance Futures **testnet** (no real money)
- **Starting budget:** $200 USDT (testnet balance — for testing only)
- **Mode env var:** `TRADING_MODE=testnet` (already set in Secret Manager)
- **Testnet dashboard:** https://testnet.binancefuture.com

### TradingView
- **Account tier:** Essentials
- **Signal source:** TradingView webhook alerts (not Pine Script API — alerts fire JSON to the bot's `/webhook` endpoint)
- **Essentials gives access to:** all built-in indicators, multi-condition alerts, webhook URL on alerts

### Strategy — TO BE DECIDED in this session
The owner will choose which instruments to trade. Cowork's job is to help pick a solid, beginner-friendly strategy that:
- Works on TradingView with built-in indicators (no paid scripts needed)
- Has clear entry/exit signals that map to BUY / SELL / CLOSE webhook actions
- Makes sense for futures (directional, not buy-and-hold)
- Fits $200 paper budget with `size_usdt` between 10–50 per trade

**Suggested starting point to evaluate together:**
- EMA crossover (fast/slow) on 15m or 1h — simple, testable, widely understood
- RSI + EMA combo — adds momentum filter to reduce false signals
- MACD signal line cross — good for trending markets

**Symbols to discuss:** Owner will choose. Good candidates for testing: `BTCUSDT`, `ETHUSDT`, `SOLUSDT` (liquid, available on Binance testnet).

### Current risk parameters (in `app/risk.py`)
```python
MAX_SIZE_USDT   = 500.0   # ← should lower to 50 for $200 budget
MAX_SL_PCT      = 3.0     # stop-loss cap
MIN_TP_SL_RATIO = 1.2     # minimum reward:risk
ALLOWED_SYMBOLS = None    # ← should whitelist chosen symbols
```
These should be updated once strategy and symbols are decided.

---

## 4. First-session test checklist

Work through this top to bottom with the owner. Check off each step.

### Phase 1 — Deployment

- [ ] GitHub secrets added (Section 2)
- [ ] GitHub Actions run succeeds (green check on `main`)
- [ ] Get Cloud Run URL:
  ```bash
  gcloud run services describe tradingbot --region=europe-west1 --project=strader-496414 --format="value(status.url)"
  ```
- [ ] Health check passes:
  ```bash
  curl <CLOUD_RUN_URL>/health
  # Expected: {"mode": "testnet", "status": "ok"}
  ```

### Phase 2 — Manual webhook test

```bash
export WEBHOOK_SECRET="<value from Secret Manager>"
# Get it: gcloud secrets versions access latest --secret=WEBHOOK_SECRET --project=strader-496414

./scripts/trigger_test_webhook.sh <CLOUD_RUN_URL> BUY
# Expected: {"status": "opened", "symbol": "BTCUSDT", ...}
```

- [ ] BUY response is `"status": "opened"`
- [ ] Position appears in Firestore:
  ```bash
  curl <CLOUD_RUN_URL>/positions
  ```
- [ ] Order visible on Binance testnet → https://testnet.binancefuture.com → Orders

```bash
./scripts/trigger_test_webhook.sh <CLOUD_RUN_URL> CLOSE
# Expected: {"status": "closed", "symbol": "BTCUSDT"}
```

- [ ] CLOSE response is `"status": "closed"`
- [ ] Positions endpoint returns empty list `[]`
- [ ] Reconcile endpoint works:
  ```bash
  curl <CLOUD_RUN_URL>/reconcile
  # Expected: {"checked": 0, "cleared": [], "timestamp": "..."}
  ```

### Phase 3 — Strategy & TradingView

- [ ] Owner picks symbol(s) and timeframe
- [ ] Cowork and owner agree on strategy (indicators, entry/exit conditions)
- [ ] Update `app/risk.py` with correct `MAX_SIZE_USDT` and `ALLOWED_SYMBOLS`, push to main
- [ ] On TradingView: open chart, add chosen indicators
- [ ] Create alert → set Webhook URL to `<CLOUD_RUN_URL>/webhook`
- [ ] Set alert message body (template in HOWTO.md Section 8b)
- [ ] Add header `X-Webhook-Secret: <secret>`
- [ ] Manually trigger alert from TradingView "Test" button if available, or wait for first real signal
- [ ] Confirm signal arrives and order opens on Binance testnet

### Phase 4 — Reconciliation cron

- [ ] Set up Cloud Scheduler (in HOWTO.md Section 10, Option A):
  ```bash
  gcloud services enable cloudscheduler.googleapis.com --project=strader-496414

  gcloud scheduler jobs create http tradingbot-reconcile \
    --location=europe-west1 \
    --schedule="*/5 * * * *" \
    --uri="<CLOUD_RUN_URL>/reconcile" \
    --http-method=GET \
    --time-zone="UTC" \
    --project=strader-496414
  ```
- [ ] Verify first scheduled run in Cloud Scheduler console

---

## 5. Possible upgrades (evaluate and implement as needed)

Priority order suggested — discuss with owner which matter for paper trading phase:

### High value, low effort
| # | Upgrade | Why |
|---|---------|-----|
| U1 | `ALLOWED_SYMBOLS` whitelist in `risk.py` | Prevents rogue/typo signals from opening unexpected positions |
| U2 | Lower `MAX_SIZE_USDT` to match $200 budget (suggest 20–50) | Avoids accidentally sending a $500 order on testnet |
| U3 | Add `size_usdt` to TradingView alert message as a dynamic variable | Lets strategy control position sizing per signal |
| U4 | `/positions` endpoint called in TradingView alert confirmation | Quick sanity check after each signal |

### Medium value
| # | Upgrade | Why |
|---|---------|-----|
| U5 | Per-symbol position sizing (% of balance instead of fixed USDT) | More realistic when scaling |
| U6 | Binance exchange filter lookup for qty precision (LOT_SIZE stepSize) | Removes the TODO in `trade_engine.py`, prevents order rejections on altcoins |
| U7 | Telegram or email notification on open/close | Owner sees every trade in real time without watching logs |
| U8 | Daily P&L summary from `trade_log` Firestore collection | Track paper performance |

### Larger scope (post paper-trading validation)
| # | Upgrade | Why |
|---|---------|-----|
| U9 | Multi-symbol dashboard (simple HTML page at `/dashboard`) | See all open positions and recent trades in one view |
| U10 | Trailing stop support in payload (`tsl_pct` field) | Better exit management for trending moves |
| U11 | Partial close (close X% of position, not 100%) | More nuanced trade management |
| U12 | Switch `TRADING_MODE` to `live` when paper results are satisfactory | The entire pipeline is already wired for it |

---

## 6. Key file locations

```
app/risk.py          ← change MAX_SIZE_USDT, ALLOWED_SYMBOLS here
app/trade_engine.py  ← core BUY/SELL/CLOSE logic
app/main.py          ← Flask routes, auth, logging
HOWTO.md             ← full step-by-step deployment reference
scripts/trigger_test_webhook.sh  ← manual test tool
```

---

## 7. Useful commands (keep handy)

```bash
# Get Cloud Run URL
gcloud run services describe tradingbot --region=europe-west1 --project=strader-496414 --format="value(status.url)"

# Get webhook secret
gcloud secrets versions access latest --secret=WEBHOOK_SECRET --project=strader-496414

# View live logs
gcloud logging read 'resource.type="cloud_run_revision" resource.labels.service_name="tradingbot"' \
  --limit=30 --format="value(jsonPayload.message)" --project=strader-496414

# Check open positions
curl <CLOUD_RUN_URL>/positions

# Trigger reconciliation
curl <CLOUD_RUN_URL>/reconcile

# Fire a test BUY
WEBHOOK_SECRET=$(gcloud secrets versions access latest --secret=WEBHOOK_SECRET --project=strader-496414) \
  ./scripts/trigger_test_webhook.sh <CLOUD_RUN_URL> BUY
```

---

## 8. Opening prompt for the cowork session

Paste this as the first message in the new Claude Code session after `cd trader-google-c`:

---

> **Cowork session start — TradingBot paper trading**
>
> Read `COWORK_HANDOFF.md` in full before doing anything. This is a working trading bot codebase — do not make any code changes until we've completed the deployment checklist in Section 4 of the handoff.
>
> **Your first job:** Walk me through Section 4 (First-session test checklist), one phase at a time. Ask me for confirmations at each checkbox. Do not skip ahead.
>
> **After deployment is verified:** Help me choose a trading strategy (Section 3 context). I will tell you which symbol(s) I want to trade today. You will suggest 2–3 strategy options with their TradingView indicator setup and explain the BUY/SELL/CLOSE signal logic for each. I pick one, you help me configure it.
>
> **Budget context:** $200 USDT on Binance testnet. We are paper trading only. Recommend appropriate `size_usdt`, `tp_pct`, and `sl_pct` values for the strategy we pick.
>
> **After the first live signal fires:** Review the Firestore position and Binance testnet order together with me to confirm everything is working correctly.
>
> **Then:** Look at Section 5 (upgrades list) and tell me which ones you'd recommend implementing today based on what we saw during testing.
>
> GCP project: `strader-496414` | Region: `europe-west1` | Repo: `saifbelaarbi/trader-google-c`
