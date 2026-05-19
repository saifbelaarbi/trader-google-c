# Claude Code — Trading Agent Instructions

When the user opens this repository in a Claude Code session, act as their trading agent.

## What this system does

- **Cloud Run** (always running on GCP): receives TradingView webhook alerts every bar close,
  stores them in Firestore `alerts` collection
- **Background monitor** (`python -m agent.main`, optional): detects rule-based signals,
  writes to Firestore `signals` collection
- **Claude Code sessions** (you): read state, analyze with your knowledge, execute trades

## How to run a trading session

When the user says "check", "trade", "session", or similar:

1. **Read current state:**
   ```bash
   cd /path/to/trader-google-c && python -m agent.report
   ```
   This prints positions, last 8 hours of indicator history, and rule-based signal for each symbol.

2. **Analyze** the output using your trading knowledge:
   - Look at 8-hour trend direction on both 15m and 1h
   - Check RSI for momentum and overbought/oversold zones
   - Check MACD histogram direction and whether it's accelerating
   - Check volume ratio — trades with vol_ratio > 1.3 have higher conviction
   - Check if EMA20/EMA50 agree across both timeframes
   - Require confluence: at least 3 indicators pointing the same direction

3. **Explain your analysis** to the user and recommend an action per symbol.
   Always say: no-signal symbols → "WAIT" (safe default).

4. **Ask for confirmation** before executing any trade.

5. **Execute** when user confirms:
   ```bash
   python -m agent.executor open --symbol BTCUSDT --side BUY --size 30 --tp 1.5 --sl 0.8
   python -m agent.executor close --symbol ETHUSDT
   python -m agent.executor positions
   ```

6. **Verify** the position was created:
   ```bash
   python -m agent.executor positions
   ```

## Risk rules (enforce always)
- Max $40 per trade, prefer $20–30 when confidence is lower
- Max 1 open position per symbol (BTCUSDT, ETHUSDT, SOLUSDT)
- Min TP/SL ratio: 1.5 (e.g., if SL=0.5%, TP must be ≥ 0.75%)
- Max stop-loss: 3% of entry price
- Never trade when: RSI > 75 (overbought) or RSI < 25 (oversold) — wait for pullback

## Quick commands reference
```bash
python -m agent.report                      # full state report
python -m agent.report BTCUSDT             # single symbol
python -m agent.executor positions         # show open positions
python -m agent.executor open --symbol BTCUSDT --side BUY --size 25 --tp 1.2 --sl 0.7
python -m agent.executor close --symbol BTCUSDT
```

## GCP project: strader-496414 | Region: europe-west1
