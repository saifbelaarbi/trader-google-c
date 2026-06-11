# Freqtrade Paper-Trading Setup (your PC)

Runs the `ClaudeConsensus` strategy (port of `agent/signals.py`) in **dry-run mode**
on your PC, 24/7, with Telegram control from your phone. No real money moves until
`dry_run` is flipped — and only after the go-live gates in `OVERHAUL_PLAN.md` pass.

---

## 1. Install Freqtrade

**Option A — Docker (recommended, works on Windows/Mac/Linux):**

```bash
# from the repo root
docker pull freqtradeorg/freqtrade:stable
```

Then prefix every `freqtrade ...` command below with:

```bash
docker run --rm -v "$(pwd)/ftbot:/freqtrade/user_data" freqtradeorg/freqtrade:stable
```

For the long-running `trade` command, drop `--rm` and add `-d --name ftbot --restart unless-stopped`
plus `-p 127.0.0.1:8080:8080` if you want the web UI.

**Option B — pip (Linux/WSL, Python 3.11+):**

```bash
python -m venv ~/ft-env && source ~/ft-env/bin/activate
pip install freqtrade
```

> With Docker, paths inside commands use `/freqtrade/user_data/...` instead of `ftbot/...`.
> The commands below are written for Option B (pip); adjust paths for Docker.

## 2. Download historical data (for backtesting)

```bash
freqtrade download-data \
  --userdir ftbot \
  --config ftbot/config.dry.json \
  --timeframes 15m 1h \
  --timerange 20240101-
```

## 3. Backtest the ported strategy — do this FIRST

```bash
freqtrade backtesting \
  --userdir ftbot \
  --config ftbot/config.dry.json \
  --strategy ClaudeConsensus \
  --timerange 20240601- \
  --breakdown month
```

This is the reality check the system never had. Paste the output into a Claude
session for analysis (win rate, profit factor, max drawdown, per-month breakdown).

## 4. Telegram (phone control)

**Create a NEW bot** with @BotFather — do **not** reuse the `saif_trader_bot` token.
The Cloud Run relay holds a webhook on that token; Freqtrade uses polling and the
two would conflict (Telegram allows only one consumer per token).

1. @BotFather → `/newbot` → copy the token into `ftbot/config.dry.json` → `telegram.token`
2. Your chat_id is the same one you already use → `telegram.chat_id`
3. Set `"enabled": true`

You then get from your phone: `/status`, `/profit`, `/daily`, `/balance`,
`/forceexit <id>`, `/stopentry`, `/start`, `/stop`, `/performance` — this replaces
most of what `cloud/main.py` did, with zero custom code to maintain.

## 5. Start paper trading

```bash
freqtrade trade \
  --userdir ftbot \
  --config ftbot/config.dry.json \
  --strategy ClaudeConsensus
```

Leave it running (Docker `--restart unless-stopped`, or `tmux`/`systemd` for pip).
Optional web dashboard: `freqtrade install-ui` then open http://127.0.0.1:8080.

## 6. Weekly review ritual (Claude session)

Once a week, open a Claude Code session on this repo and paste in:

```bash
freqtrade backtesting-analysis --userdir ftbot --config ftbot/config.dry.json
# or for live dry-run results:
sqlite3 ftbot/tradesv3.dryrun.sqlite "select * from trades order by close_date desc limit 30;"
```

Claude analyzes: where the edge concentrates (pair / regime / hour), which signals
predict winners, what to tune next — then proposes a hyperopt run.

## 7. Optimization (after first backtest results)

```bash
freqtrade hyperopt \
  --userdir ftbot \
  --config ftbot/config.dry.json \
  --strategy ClaudeConsensus \
  --hyperopt-loss SharpeHyperOptLoss \
  --spaces buy sell \
  --timerange 20240601- \
  -e 200
```

(Requires converting strategy thresholds to hyperopt parameters first — see
Phase 2 in `OVERHAUL_PLAN.md`.)

---

## What stays on GCP

- **Cloud Run + Telegram relay**: keeps running unchanged for now (signal pings,
  `/status` on the old bot). Retire it once dry-run is stable.
- **Firestore**: stays as the trade journal for the old system; Freqtrade keeps
  its own sqlite DB locally.
- **TradingView webhooks**: no longer needed for the Freqtrade path — it pulls
  OHLCV directly from Bybit via ccxt.
