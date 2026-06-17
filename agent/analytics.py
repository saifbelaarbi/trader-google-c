"""
Trade performance stats — reads from Firestore trade_log.

Usage:
    python -m agent.analytics            # last 30 days
    python -m agent.analytics --days 7   # last 7 days
    python -m agent.analytics --days 90  # last 90 days
"""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        pass

from agent import state


def _fetch_trades(days: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    trades = []
    for fields in state.get_trade_log(cutoff_iso=cutoff):
        event = str(fields.get("event", ""))
        if "opened" in event:
            continue
        pnl = fields.get("pnl")
        if pnl is None:
            continue
        trades.append({
            "symbol": str(fields.get("symbol", "?")),
            "pnl": float(pnl),
            "event": event,
            "timestamp": str(fields.get("timestamp", "")),
        })
    return sorted(trades, key=lambda x: x["timestamp"])


def analytics(days: int = 30) -> None:
    trades = _fetch_trades(days)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    print(f"\n{'=' * 62}")
    print(f"  TRADE ANALYTICS — last {days} days  ({now})")
    print(f"{'=' * 62}")

    if not trades:
        print(f"\n  No closed trades in the last {days} days.\n")
        print(f"{'=' * 62}\n")
        return

    wins   = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades)
    win_rate  = len(wins) / len(trades) * 100
    avg_win   = sum(t["pnl"] for t in wins) / len(wins) if wins else 0.0
    avg_loss  = sum(t["pnl"] for t in losses) / len(losses) if losses else 0.0

    if avg_loss != 0:
        rr_str = f"{abs(avg_win / avg_loss):.2f}×"
    else:
        rr_str = "∞ (no losses)"

    # Max drawdown — peak-to-trough on cumulative P&L curve
    cumulative, peak, max_dd = 0.0, 0.0, 0.0
    for t in trades:
        cumulative += t["pnl"]
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)

    print(f"\n  Trades         : {len(trades)}  ({len(wins)} wins / {len(losses)} losses)")
    print(f"  Win rate       : {win_rate:.1f}%")
    print(f"  Total P&L      : ${total_pnl:+.2f}")
    print(f"  Avg win        : ${avg_win:+.2f}")
    print(f"  Avg loss       : ${avg_loss:+.2f}")
    print(f"  Avg R:R        : {rr_str}")
    print(f"  Max drawdown   : ${max_dd:.2f}")

    # Per-symbol
    by_symbol: dict[str, dict] = {}
    for t in trades:
        sym = t["symbol"]
        if sym not in by_symbol:
            by_symbol[sym] = {"pnl": 0.0, "trades": 0, "wins": 0}
        by_symbol[sym]["pnl"] += t["pnl"]
        by_symbol[sym]["trades"] += 1
        if t["pnl"] > 0:
            by_symbol[sym]["wins"] += 1

    print(f"\n  {'Symbol':<12} {'Trades':>6} {'Wins':>5} {'Win%':>6} {'P&L':>10}")
    print(f"  {'-' * 47}")
    for sym, s in sorted(by_symbol.items()):
        sym_wr = s["wins"] / s["trades"] * 100 if s["trades"] else 0
        print(f"  {sym:<12} {s['trades']:>6} {s['wins']:>5} {sym_wr:>5.0f}%  {s['pnl']:>+9.2f}")

    # Last 10 closed trades
    print(f"\n  Recent trades (last 10):")
    print(f"  {'Time':<17} {'Symbol':<10} {'Event':<20} {'P&L':>9}")
    print(f"  {'-' * 60}")
    for t in trades[-10:]:
        ts_short = t["timestamp"][:16].replace("T", " ")
        print(f"  {ts_short:<17} {t['symbol']:<10} {t['event']:<20} {t['pnl']:>+9.2f}")

    print(f"\n{'=' * 62}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trade performance analytics")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days")
    args = parser.parse_args()
    analytics(args.days)
