"""
Trading state report — run this from Claude Code to get a full picture.

Usage:
    python -m agent.report            # all symbols
    python -m agent.report BTCUSDT    # single symbol
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        pass

from agent import broker as _broker_mod, signals, state
from agent.config import HISTORY_15M, HISTORY_1H, SYMBOLS, TIMEFRAME_15M, TIMEFRAME_1H


def _fmt_ts(val) -> str:
    if val is None:
        return "???"
    if hasattr(val, "strftime"):
        return val.strftime("%m-%d %H:%M UTC")
    return str(val)[:16]


def _fmt_table(alerts: list[dict], n: int = 8) -> str:
    if not alerts:
        return "    (no data)\n"
    rows = [
        "    time          | price      | ema20      | ema50      | rsi14 | macd_hist  | atr14   | vol_x",
        "    " + "-" * 93,
    ]
    for a in alerts[-n:]:
        rows.append(
            f"    {_fmt_ts(a.get('received_at')):<16}| "
            f"{a.get('price') or 0:10.2f} | "
            f"{a.get('ema20') or 0:10.2f} | "
            f"{a.get('ema50') or 0:10.2f} | "
            f"{a.get('rsi14') or 0:5.1f} | "
            f"{a.get('macd_hist') or 0:10.4f} | "
            f"{a.get('atr14') or 0:7.2f} | "
            f"{a.get('vol_ratio') or 0:5.2f}"
        )
    return "\n".join(rows)


def report(symbols: list[str]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'=' * 70}")
    print(f"  TRADING BOT STATE REPORT — {now}")
    print(f"{'=' * 70}")

    all_positions = state.get_all_positions()
    print(f"\n  Open positions: {len(all_positions)}")
    try:
        b = _broker_mod.active()
    except Exception:
        b = None
    for p in all_positions:
        sym = p["symbol"]
        side = p.get("side", "BUY")
        entry = float(p.get("entry_price") or 0)
        qty = float(p.get("qty") or 0)
        size = float(p.get("size_usdt") or 0)
        pnl_str = ""
        if b and entry and qty:
            try:
                now_price = b.get_price(sym)
                pnl = (now_price - entry) * qty if side == "BUY" else (entry - now_price) * qty
                pnl_pct = (now_price - entry) / entry * 100 if side == "BUY" else (entry - now_price) / entry * 100
                pnl_str = f" | now=${now_price:,.2f} | P&L: ${pnl:+.2f} ({pnl_pct:+.2f}%)"
            except Exception:
                pass
        print(
            f"    {sym}: {side} | entry=${entry:,.2f}"
            f" tp={p.get('tp')} sl={p.get('sl')} size=${size}{pnl_str}"
        )
    if not all_positions:
        print("    None")

    for symbol in symbols:
        print(f"\n{'─' * 70}")
        print(f"  {symbol}")
        print(f"{'─' * 70}")

        position = next((p for p in all_positions if p["symbol"] == symbol), None)
        alerts_15m = state.get_recent_alerts(symbol, TIMEFRAME_15M, HISTORY_15M)
        alerts_1h = state.get_recent_alerts(symbol, TIMEFRAME_1H, HISTORY_1H)

        print("\n  15m history (last 8 bars shown):")
        print(_fmt_table(alerts_15m, n=8))
        print("\n  1h history (last 8 bars):")
        print(_fmt_table(alerts_1h, n=8))

        signal = signals.evaluate(alerts_15m, alerts_1h, position)
        action = signal.get("action", "WAIT")
        print(f"\n  Rule-based signal: {action}")
        print(f"    Bull indicators : {signal.get('bull_signals', '?')}/6")
        print(f"    Bear indicators : {signal.get('bear_signals', '?')}/6")
        print(f"    RSI14           : {signal.get('rsi', '?')}")
        print(f"    MACD hist       : {signal.get('macd_hist', '?')}")
        print(f"    Vol ratio       : {signal.get('vol_ratio', '?')}")
        print(f"    EMA trend 15m   : {signal.get('ema_trend_15m', '?')}")
        print(f"    EMA trend 1h    : {signal.get('ema_trend_1h', '?')}")
        if action in ("OPEN_LONG", "OPEN_SHORT"):
            print(f"    Suggested size  : ${signal.get('size_usdt')}")
            print(f"    TP %            : {signal.get('tp_pct')}")
            print(f"    SL %            : {signal.get('sl_pct')}")
        if signal.get("reason"):
            print(f"    Reason          : {signal.get('reason')}")

    print(f"\n{'=' * 70}\n")


if __name__ == "__main__":
    target = sys.argv[1:] if len(sys.argv) > 1 else SYMBOLS
    report([s.upper() for s in target])
