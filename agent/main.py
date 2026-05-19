"""
Background signal monitor — runs on your PC, does NOT execute trades.

Polls Firestore for new TradingView alerts, evaluates rule-based signals,
and writes detected signals to the Firestore `signals` collection so
Claude Code can review and execute them in a live session.

Usage:
    python -m agent.main

Required env (agent/.env):
    BINANCE_API_KEY, BINANCE_API_SECRET, TRADING_MODE=testnet
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa-key.json  (or gcloud ADC)
"""

import logging
import sys
import time
from pathlib import Path

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        pass

from agent import signals, state
from agent.config import (
    HISTORY_15M,
    HISTORY_1H,
    POLL_INTERVAL_SECONDS,
    SYMBOLS,
    TIMEFRAME_15M,
    TIMEFRAME_1H,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("monitor")

_last_alert_at: dict[str, object] = {sym: None for sym in SYMBOLS}
_last_signal: dict[str, str] = {sym: "WAIT" for sym in SYMBOLS}


def _newer(a, b) -> bool:
    if a is None:
        return False
    if b is None:
        return True
    try:
        return a.timestamp() > b.timestamp()
    except AttributeError:
        return str(a) > str(b)


def _monitor_symbol(symbol: str) -> None:
    alerts_15m = state.get_recent_alerts(symbol, TIMEFRAME_15M, HISTORY_15M)
    if not alerts_15m:
        return

    latest_at = alerts_15m[-1].get("received_at")
    if not _newer(latest_at, _last_alert_at[symbol]):
        return  # No new bar

    alerts_1h = state.get_recent_alerts(symbol, TIMEFRAME_1H, HISTORY_1H)
    position = state.get_position(symbol)

    signal = signals.evaluate(alerts_15m, alerts_1h, position)
    action = signal.get("action", "WAIT")

    if action != _last_signal[symbol]:
        logger.info(
            "%s signal changed: %s → %s  (bull=%s bear=%s rsi=%.1f)",
            symbol, _last_signal[symbol], action,
            signal.get("bull_signals"), signal.get("bear_signals"), signal.get("rsi", 0),
        )

    if action not in ("WAIT", "HOLD"):
        from google.cloud import firestore
        entry = {"symbol": symbol, "action": action, **signal, "timestamp": firestore.SERVER_TIMESTAMP}
        state._get_db().collection("signals").add(entry)
        logger.info("%s: Signal written to Firestore — open Claude Code to review and execute", symbol)

    _last_alert_at[symbol] = latest_at
    _last_signal[symbol] = action


def main() -> None:
    logger.info("Signal monitor starting | symbols=%s | interval=%ss", SYMBOLS, POLL_INTERVAL_SECONDS)
    logger.info("NOTE: This process detects signals only — trades execute via Claude Code")
    while True:
        for symbol in SYMBOLS:
            try:
                _monitor_symbol(symbol)
            except Exception:
                logger.error("Error monitoring %s", symbol, exc_info=True)
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
