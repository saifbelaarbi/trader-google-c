# TradingBot

TradingView → Cloud Run → Firestore → Claude Code → Bybit testnet.

Claude is the trading brain. Cloud Run is a relay. Telegram is the notification channel.

---

## Architecture

```
TradingView alerts (15m + 1h bar close)
  └── POST /webhook  (X-Webhook-Secret header)
         │
         ▼
┌─────────────────────────────────────────┐
│  Cloud Run  (europe-west1)              │
│  tradingbot-grpyjoqoaq-ew.a.run.app     │
│                                         │
│  /webhook   → store alert in Firestore  │
│  /state     → positions + indicators    │
│  /reconcile → sync Bybit ↔ Firestore   │
│  /health    → liveness                  │
│  /telegram-webhook → bot commands       │
└──────────┬───────────────────┬──────────┘
           │                   │
           ▼                   ▼
    ┌─────────────┐    ┌──────────────┐
    │  Firestore  │    │   Telegram   │
    │  alerts     │    │  saif_trader │
    │  positions  │    │  _bot        │
    │  trade_log  │    └──────────────┘
    └──────┬──────┘
           │ REST API (gRPC blocked in container)
           ▼
  Claude Code session
    python -m agent.report    ← read live data
    python -m agent.executor  ← place trades
           │
           ▼
    ┌──────────────┐
    │  Bybit       │
    │  testnet     │
    │  USDT perps  │
    │  $200 budget │
    └──────────────┘
```

---

## TradingView alert payload (what gets stored in Firestore)

```json
{
  "symbol":    "BTCUSDT",
  "timeframe": "15",
  "price":     65000.0,
  "ema20":     64800.0,
  "ema50":     64200.0,
  "rsi14":     58.3,
  "macd_hist": 45.2,
  "atr14":     320.5,
  "vol_ratio": 1.2
}
```

---

## Quick start (new session)

```bash
# State is auto-configured by .claude/setup-session.sh
# Just run:
python -m agent.report

# Then execute trades Claude recommends:
python -m agent.executor open --symbol BTCUSDT --side BUY --size 25 --tp 1.5 --sl 0.8
python -m agent.executor close --symbol BTCUSDT
python -m agent.executor positions
```

---

## Key files

| File | Role |
|------|------|
| `CLAUDE.md` | Trading instructions for Claude (analysis, risk rules, commands) |
| `HOWTO.md` | Setup guide + operations reference |
| `TODO.md` | Roadmap — what's done, what's next |
| `COWORK_HANDOFF.md` | Session handoff + opening prompt |
| `cloud/main.py` | Cloud Run Flask app (webhook relay, endpoints, auto-trade thread) |
| `cloud/telegram.py` | Telegram notification helpers |
| `agent/state.py` | Firestore REST API layer (reads/writes alerts, positions, trade_log) |
| `agent/signals.py` | 6-point signal engine (MACD accel, EMA slope, dynamic sizing) |
| `agent/report.py` | Live state report — run this every session |
| `agent/executor.py` | Trade execution tool for Claude |
| `agent/risk.py` | Hard risk rules (size cap, TP/SL ratio, max SL%) |
| `agent/brokers/bybit.py` | Bybit USDT perps broker |
| `.claude/setup-session.sh` | Auto-runs at session start — loads creds, installs deps, pings Telegram |

---

## Cloud Run endpoints

| Method | Path | Auth |
|--------|------|------|
| GET | `/health` | None |
| POST | `/webhook` | `X-Webhook-Secret` header |
| GET | `/state` | None |
| GET | `/indicators/<symbol>` | None |
| GET | `/positions` | None |
| GET | `/reconcile` | None |
| POST | `/telegram-webhook` | Telegram verifies chat_id |

---

## CI/CD

Push to `main` → GitHub Actions:
1. `ruff check cloud/ tests/`
2. `pytest tests/ -v`
3. Docker build → Artifact Registry
4. `gcloud run deploy tradingbot --region europe-west1`

Secrets are mounted from GCP Secret Manager (not GitHub secrets).

---

## GCP project

```
Project:  tradingbot-496815
Region:   europe-west1
SA:       tradingbot-sa@tradingbot-496815.iam.gserviceaccount.com
```
