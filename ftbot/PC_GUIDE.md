# Fqtrader — Complete PC Usage Guide

**Scope:** everything you do on your PC to run, monitor, and improve the freqtrade
trading system in `ftbot/`. This is the operational companion to the strategy research
in `ftbot/RESEARCH_returns.md` (the *why*) — this document is the *how*.

> **Cloud vs PC.** Claude Code cloud sessions cannot reach Bybit or run freqtrade
> (no exchange/market-data access, no TA-Lib). Everything in §3–§7 runs on **your PC**.
> Cloud sessions are for analysis, code, and planning only.

> **Golden rule.** The live paper bot runs **`ClaudeBreakout`**. Do **not** change its
> parameters or logic during the paper-trading window — that invalidates the
> experiment. All tuning happens on the *research* variants in backtests (§6), and is
> promoted only after the go-live gates pass (§8). See `CLAUDE.md`.

---

## 1. What you are running

| Layer | What | Where |
|---|---|---|
| Trading engine | freqtrade `ClaudeBreakout`, 4h Donchian breakout, dry-run | your PC, 24/7 |
| Phone control | freqtrade's native Telegram bot | your phone |
| Research / R&D | backtests, hyperopt, analysis | PC (run) + Claude cloud (interpret) |

**Strategy in one line:** enter on a 20-bar Donchian high/low break filtered by EMA200,
exit on the opposite 10-bar extreme, hard stop at 2×ATR. 9 USDT-perp pairs, max 4 open,
$200 dry-run wallet. Backtest reference (2024-06→2026-06): +40.9%, PF 1.15, win 30.8%,
max DD 25.9%, ~0.8 trades/day.

**Files you touch:**

```
ftbot/
  config.dry.json            # bot config — holds YOUR local secrets (never commit them)
  start-bot.bat / .ps1       # one-click: pull main + start the dry-run bot
  watch-bot.bat / .ps1       # same, auto-redeploys on each main push touching ftbot/
  strategies/
    ClaudeBreakout.py        # LIVE strategy — do not edit mid-window
    breakout_variants.py     # parameter neighbours (robustness, backtest only)
    breakout_research.py     # research levers: Risk/Corr/Pyramid/Chandelier/Pro
    breakout_hyperopt.py     # ClaudeBreakoutHO — hyperopt-ready
    research_sizing.py       # pure sizing math (unit-tested)
    README.md                # strategies index
  RESEARCH_returns.md        # the returns-optimization research
  PC_GUIDE.md                # this file
```

---

## 2. Install freqtrade

### Option A — Docker (recommended; Windows/Mac/Linux)

```bash
docker pull freqtradeorg/freqtrade:stable
```

Prefix every `freqtrade …` command with (run from the repo root):

```bash
docker run --rm -v "$PWD/ftbot:/freqtrade/user_data" freqtradeorg/freqtrade:stable
```

For the long-running bot, drop `--rm` and add
`-d --name ftbot --restart unless-stopped -p 127.0.0.1:8080:8080`.

> With Docker, paths inside commands become `/freqtrade/user_data/…` instead of
> `ftbot/…`, and `--userdir /freqtrade/user_data`.

### Option B — pip (Linux/WSL/macOS, Python 3.11+)

```bash
python -m venv ~/ft-env
source ~/ft-env/bin/activate      # Windows: ~\ft-env\Scripts\activate
pip install freqtrade             # pulls TA-Lib wheels on supported platforms
freqtrade --version
```

The commands below use Option B paths (`ftbot/…`); adjust for Docker as noted.

---

## 3. One-time setup

### 3a. Secrets in `config.dry.json`

The working-tree `config.dry.json` ships with placeholders. Fill in **locally** and
**never commit** the real values (the repo keeps placeholders on purpose):

- `telegram.token` — a **new** bot token from @BotFather. Do **not** reuse
  `saif_trader_bot` (the Cloud Run relay holds a webhook on it; freqtrade polls; the
  two conflict — Telegram allows one consumer per token).
- `telegram.chat_id` — your existing chat id.
- `telegram.enabled` — set `true`.
- `api_server.jwt_secret_key`, `ws_token`, `password` — random strings.

### 3b. Download history

Live bot needs none, but backtests/hyperopt do. The strategy is 4h:

```bash
# enough history for the current backtest window
freqtrade download-data --userdir ftbot --config ftbot/config.dry.json \
  --timeframes 4h --timerange 20240101-

# for multi-regime confidence (2021 bull, 2022 bear) — see RESEARCH_returns §8
freqtrade download-data --userdir ftbot --config ftbot/config.dry.json \
  --timeframes 4h --timerange 20210101-
```

Futures funding data is pulled automatically for `trading_mode: futures`.

---

## 4. Run the live paper bot

### Easiest — the batch scripts

```powershell
ftbot\start-bot.bat     # pulls main, preserves your local secrets, starts dry-run
ftbot\watch-bot.bat     # same, and auto-redeploys whenever main changes ftbot/ (dry-run only)
```

### Or directly

```bash
freqtrade trade --userdir ftbot --config ftbot/config.dry.json --strategy ClaudeBreakout
```

Keep it running 24/7: Docker `--restart unless-stopped`, or `tmux`/`systemd` (pip).
Optional dashboard: `freqtrade install-ui`, then http://127.0.0.1:8080.

You'll get a **breakout radar** Telegram push each 4h candle: per-pair bias and distance
to the next Donchian trigger, plus open positions.

---

## 5. Monitor from your phone

Telegram commands (freqtrade native):

| Command | Shows |
|---|---|
| `/status` | open trades + live P&L |
| `/profit` | cumulative profit summary |
| `/performance` | profit by pair |
| `/daily`, `/weekly`, `/monthly` | P&L by period |
| `/balance` | wallet |
| `/forceexit <id>` / `/forceexit all` | manual close (kill switch) |
| `/stopentry` | stop new entries, keep managing open ones |
| `/stop` / `/start` | halt / resume the bot |
| `/count` | open vs max trades |

### Weekly review ritual (the main cadence)

Once a week, paste into a Claude cloud session for analysis:

```bash
# live dry-run trades
sqlite3 ftbot/tradesv3.dryrun.sqlite \
  "select pair, is_short, open_date, close_date, close_profit, exit_reason \
   from trades order by close_date desc limit 30;"
```

Or paste `/profit`, `/performance`, `/status` output. Compare against the backtest
profile: win ~30%, winners avg ~+5% over ~6 days (Donchian exit), losers ~-4%
(stop/trail). **Flag divergence; do not tune mid-window.** Losing streaks past 20 are
within backtest norms — not a malfunction.

---

## 6. Research workflow (backtests on PC, interpret with Claude)

This is how you make the system better — all on the *research* variants, never the live
bot. Full rationale: `RESEARCH_returns.md`. Do the steps **in order**.

### Step 0 — Realism FIRST (decides if the edge is real)

Re-run the baseline with funding + a slippage assumption before building anything. A
gross PF 1.15 can become net ~1.0 once you enter *into* momentum and pay funding on
multi-day holds.

```bash
freqtrade backtesting --userdir ftbot --config ftbot/config.dry.json \
  --strategy ClaudeBreakout --timerange 20210101- --breakdown month
```

Add a slippage/fee assumption via config and confirm the net profit factor. If the
honest PF ≤ 1.0, stop and rethink — don't tune a non-edge.

### Step 1 — A/B the levers against the live baseline

The research variants (built on `ClaudeBreakout`) each isolate one lever:

| Strategy | Lever |
|---|---|
| `ClaudeBreakout` | baseline (live) |
| `ClaudeBreakoutRisk` | volatility-targeted unit sizing |
| `ClaudeBreakoutCorr` | + correlation/crowding down-scaling |
| `ClaudeBreakoutPyramid` | + Turtle pyramiding |
| `ClaudeBreakoutChandelier` | + chandelier trailing exit |
| `ClaudeBreakoutPro` | all levers combined |

```bash
freqtrade backtesting --userdir ftbot --config ftbot/config.dry.json \
  --strategy-list ClaudeBreakout ClaudeBreakoutRisk ClaudeBreakoutCorr \
                  ClaudeBreakoutPyramid ClaudeBreakoutChandelier ClaudeBreakoutPro \
  --timerange 20240601- --breakdown month
```

### Step 2 — Read the results the right way

Win rate is a red herring (this is a low-win, high-payoff system). Judge on:

- **Profit factor (PF)** — gross-profit / gross-loss, *net of fees+funding*.
- **Calmar** — return ÷ max drawdown. This is the primary metric (the go-live gate is a
  drawdown gate). Prefer a variant that lifts Calmar, not just raw return.
- **Max drawdown** — must stay within the gate (≤ ~26%, ideally lower).
- **Expectancy / payoff ratio** — avg-win ÷ avg-loss; the levers should fatten this.
- **Per-month / per-pair breakdown** — confirm the edge isn't one pair or one quarter.

### Step 3 — Walk-forward hyperopt (the "smarter" tuning)

`ClaudeBreakoutHO` exposes entry/exit windows, trend EMA, ATR stop, and risk fraction
as tunable parameters. **Optimise on history, validate untouched on a held-out period.**

```bash
# optimise on 2021–2024
freqtrade hyperopt --userdir ftbot --config ftbot/config.dry.json \
  --hyperopt-loss CalmarHyperOptLoss --strategy ClaudeBreakoutHO \
  --timerange 20210101-20241231 --epochs 300 --spaces buy sell stoploss

# then VALIDATE the chosen params, unchanged, on 2025+
freqtrade backtesting --userdir ftbot --config ftbot/config.dry.json \
  --strategy ClaudeBreakoutHO --timerange 20250101- --breakdown month
```

**Adopt a parameter *region*, not the single best epoch** — a real edge is a plateau, a
spike is noise. The robustness table in `OVERHAUL_PLAN.md` already shows the slow
gradient (30/15, EMA250) is the promising direction.

### Step 4 — Decision rule

Keep a change only if it improves **Calmar on the validation period, net of
funding+slippage**, without breaking the drawdown gate. One change per backtest so
attribution stays clean. Bring the numbers to a Claude cloud session to sanity-check.

---

## 7. Optional deeper analysis

- **Monte-Carlo / trade-order shuffle** on the winning config to budget the 95th-pct
  drawdown — the single realised 25.9% DD is one sample; size against the distribution.
- **`freqtrade backtesting-analysis`** for entry/exit-reason and per-pair attribution.
- **`freqtrade plot-dataframe` / `plot-profit`** for visual sanity checks.

---

## 8. Go-live gates (ALL must pass before real money)

From `OVERHAUL_PLAN.md` §4 — these are the profit plan, do not weaken them:

- [ ] ≥ 4 weeks dry-run **and** ≥ 30 closed trades
- [ ] Dry-run profit factor ≥ 1.3, win rate within ~10 pts of backtest
- [ ] Max dry-run drawdown ≤ 15% of wallet
- [ ] No unexplained backtest-vs-dry-run divergence

Then: live Bybit keys, start with **$50–100** (not full capital), **halve** position
sizes for the first 2 weeks, and **tighten** the `MaxDrawdown` protection. Test one
manual trade before enabling autonomous entries; watch the first 5 live trades closely.

---

## 9. Safety rules (read once, keep)

1. **Never** edit `ClaudeBreakout.py` or its parameters during the paper window.
2. **Never** commit your filled-in secrets in `config.dry.json` (Telegram token, jwt,
   password) — the repo keeps placeholders.
3. Research variants are **backtest-only** — none are wired into the live config.
4. Dry-run always **flatters**: real fills slip, funding drags, fees bite. The gates and
   the realism pass (§6 step 0) exist because skipping them is the fastest way to lose
   the real bankroll.
5. One hypothesis tweak per week max — no constant fiddling.

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| Telegram silent | `telegram.enabled:true`, correct token/chat_id, bot `/start`ed, token not reused by the relay |
| "No data" in backtest | run `download-data` for `4h` over the timerange first |
| Bot won't start after edit | `git stash` local config, `git pull`, re-apply secrets (this is what `start-bot.bat` automates) |
| Port 8080 in use | change `api_server.listen_port` or stop the other process |
| Hyperopt overfits | widen the validation window, prefer `CalmarHyperOptLoss`, adopt a region not a point |
| Strategy not found | check `--userdir ftbot` and the class name matches the file |

---

## 11. Quick command reference

```bash
# download 4h data
freqtrade download-data --userdir ftbot --config ftbot/config.dry.json --timeframes 4h --timerange 20210101-

# run live paper bot
freqtrade trade --userdir ftbot --config ftbot/config.dry.json --strategy ClaudeBreakout

# baseline backtest (with realism assumptions configured)
freqtrade backtesting --userdir ftbot --config ftbot/config.dry.json --strategy ClaudeBreakout --timerange 20210101- --breakdown month

# lever A/B matrix
freqtrade backtesting --userdir ftbot --config ftbot/config.dry.json \
  --strategy-list ClaudeBreakout ClaudeBreakoutRisk ClaudeBreakoutCorr ClaudeBreakoutPyramid ClaudeBreakoutChandelier ClaudeBreakoutPro \
  --timerange 20240601- --breakdown month

# walk-forward hyperopt + validation
freqtrade hyperopt   --userdir ftbot --config ftbot/config.dry.json --hyperopt-loss CalmarHyperOptLoss --strategy ClaudeBreakoutHO --timerange 20210101-20241231 --epochs 300 --spaces buy sell stoploss
freqtrade backtesting --userdir ftbot --config ftbot/config.dry.json --strategy ClaudeBreakoutHO --timerange 20250101- --breakdown month

# inspect live dry-run trades
sqlite3 ftbot/tradesv3.dryrun.sqlite "select pair,is_short,close_date,close_profit,exit_reason from trades order by close_date desc limit 30;"
```

---

*Generated for the `trader-google-c` / `ftbot` freqtrade workstream. Pair this with
`RESEARCH_returns.md` (rationale) and `strategies/README.md` (file index).*
