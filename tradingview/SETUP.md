# TradingView Alert Setup

## Step 1 — Add the indicator to each chart

Add `indicators.pine` to each chart you want to monitor:

1. Open TradingView → chart for **BTCUSDT** on **15m** timeframe
2. Click **Indicators** (top toolbar) → **Pine Editor** → paste `indicators.pine` → **Add to chart**
3. Repeat for **BTCUSDT 1h**, **ETHUSDT 15m**, **ETHUSDT 1h**, **SOLUSDT 15m**, **SOLUSDT 1h**

That's **6 charts × 1 indicator = 6 indicators total**.

## Step 2 — Create one alert per chart

For each chart:

1. Click the **Alerts** clock icon → **Create Alert**
2. **Condition**: TradeBot Signals → **Bar Close (send to bot)**
3. **Trigger**: Once Per Bar Close
4. **Alert actions**: tick **Webhook URL**
5. **Webhook URL**: `https://<your-cloud-run-url>/webhook`
6. **Message** (paste from `webhook_template.json`):

```json
{
  "symbol": "{{ticker}}",
  "timeframe": "{{interval}}",
  "price": {{close}},
  "ema20": {{plot("EMA20")}},
  "ema50": {{plot("EMA50")}},
  "rsi14": {{plot("RSI14")}},
  "macd_hist": {{plot("MACDHist")}},
  "atr14": {{plot("ATR14")}},
  "vol_ratio": {{plot("VolRatio")}}
}
```

7. **Advanced → Additional Headers**:
   ```
   X-Webhook-Secret: <your WEBHOOK_SECRET from GCP Secret Manager>
   ```
8. Set expiry to **Open-ended** (or as far out as TradingView allows)
9. Click **Create**

## Step 3 — Verify

After the first bar closes (up to 15 minutes), check Firestore:

```bash
# In GCP Console → Firestore → alerts collection
# Or via curl:
curl https://<cloud-run-url>/health
```

Your `alerts` collection should start populating with documents like:
```json
{
  "symbol": "BTCUSDT",
  "timeframe": "15",
  "price": 65123.45,
  "ema20": 64980.0,
  "ema50": 64500.0,
  "rsi14": 58.3,
  "macd_hist": 45.2,
  "atr14": 320.5,
  "vol_ratio": 1.2
}
```

## Timeframe note

TradingView sends `{{interval}}` as:
- `"15"` for 15-minute charts
- `"60"` for 1-hour charts

These match `TIMEFRAME_15M = "15"` and `TIMEFRAME_1H = "60"` in `agent/config.py`.

## Visual reference indicators (optional but recommended)

Add these built-in TradingView indicators to your charts for visual context:
- **EMA** (period 20, colour blue) — overlaid on price
- **EMA** (period 50, colour orange) — overlaid on price
- **RSI** (period 14) — separate pane
- **MACD** (12, 26, 9) — separate pane
