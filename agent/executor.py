"""
Trade executor — called by Claude Code during a session to execute decisions.

Usage (Claude Code will call these):
    python -m agent.executor open --symbol BTCUSDT --side BUY --size 30 --tp 1.5 --sl 0.8
    python -m agent.executor close --symbol BTCUSDT
    python -m agent.executor positions
"""

import argparse
import json
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

import os

from agent import broker, risk, state
from agent.config import SYMBOLS

_MODE_BANNERS = {
    "live":    "🔴  LIVE TRADING — REAL MONEY AT RISK",
    "testnet": "🟡  TESTNET — paper money only",
}


def _print_mode_banner() -> None:
    mode = os.environ.get("TRADING_MODE", "").strip().lower()
    if not mode:
        print("=" * 62)
        print("⚠️   TRADING_MODE NOT SET — refusing to execute")
        print("    Set TRADING_MODE=testnet or TRADING_MODE=live")
        print("=" * 62)
        sys.exit(1)
    banner = _MODE_BANNERS.get(mode, f"MODE={mode}")
    print("=" * 62)
    print(f"  {banner}")
    print("=" * 62)


def cmd_open(args) -> None:
    _print_mode_banner()
    symbol = args.symbol.upper()
    side = args.side.upper()
    size_usdt = float(args.size)
    tp_pct = float(args.tp)
    sl_pct = float(args.sl)

    # Get current price from latest Firestore alert
    from agent.config import TIMEFRAME_15M
    latest = state.get_latest_alert(symbol, TIMEFRAME_15M)
    if latest is None:
        print(json.dumps({"error": f"No alert data for {symbol} — wait for TradingView bar"}))
        sys.exit(1)

    price = float(latest.get("price") or 0)
    if price == 0:
        print(json.dumps({"error": "Latest alert has no price"}))
        sys.exit(1)

    position = state.get_position(symbol)
    decision = {
        "action": "OPEN_LONG" if side == "BUY" else "OPEN_SHORT",
        "size_usdt": size_usdt,
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
    }

    error = risk.validate_decision(symbol, decision, position)
    if error:
        print(json.dumps({"error": f"Risk check failed: {error}"}))
        sys.exit(1)

    size_usdt = float(decision["size_usdt"])  # may have been capped
    qty = round(size_usdt / price, 3)
    if qty == 0:
        print(json.dumps({"error": f"Qty rounds to 0 — price={price} size={size_usdt}"}))
        sys.exit(1)

    # M6: TP1 = user's --tp (partial close), TP2 = 2× --tp (final target)
    # M7: trailing at 0.5×SL distance, activates at 1.5× TP1
    tp2_pct       = round(tp_pct * 2.0, 2)
    trail_pct     = round(sl_pct * 0.5, 2)
    if side == "BUY":
        tp1_price    = round(price * (1 + tp_pct / 100), 2)
        tp2_price    = round(price * (1 + tp2_pct / 100), 2)
        sl_price     = round(price * (1 - sl_pct / 100), 2)
        trail_active = round(price * (1 + tp_pct * 1.5 / 100), 2)
    else:
        tp1_price    = round(price * (1 - tp_pct / 100), 2)
        tp2_price    = round(price * (1 - tp2_pct / 100), 2)
        sl_price     = round(price * (1 + sl_pct / 100), 2)
        trail_active = round(price * (1 - tp_pct * 1.5 / 100), 2)
    trail_distance = round(price * trail_pct / 100, 2)

    print(f"Placing {side} {symbol} | size=${size_usdt} qty={qty} price≈{price} "
          f"tp1={tp1_price} tp2={tp2_price} sl={sl_price} trail={trail_distance}@{trail_active}")

    order = broker.place_market_order(symbol, side, qty)
    pos_data = {
        "symbol": symbol, "side": side, "entry_price": price,
        "qty": qty, "tp": tp1_price, "tp2": tp2_price, "sl": sl_price,
        "size_usdt": size_usdt, "order_id": order.get("orderId"),
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    state.save_position(symbol, pos_data)

    try:
        broker.set_tp_sl(symbol, side, qty, tp1_price, sl_price, tp2_price=tp2_price)
    except Exception as e:
        print(f"Warning: set_tp_sl failed ({e}) — position saved, manage manually")

    try:
        broker.set_trailing_stop(symbol, trail_distance, active_price=trail_active)
    except Exception as e:
        print(f"Warning: set_trailing_stop failed ({e})")

    state.log_trade({"event": "opened", **pos_data})
    print(json.dumps({"status": "opened", **pos_data}))


def cmd_close(args) -> None:
    _print_mode_banner()
    symbol = args.symbol.upper()
    position = state.get_position(symbol)
    if position is None:
        print(json.dumps({"error": f"No open position for {symbol}"}))
        sys.exit(1)

    result = broker.close_position(symbol)
    state.clear_position(symbol)
    state.log_trade({
        "event": "closed_by_agent",
        "symbol": symbol,
        "side": position.get("side"),
        "entry_price": position.get("entry_price"),
        "close_order": result,
    })
    print(json.dumps({"status": "closed", "symbol": symbol}))


def cmd_positions(_args) -> None:
    positions = state.get_all_positions()
    print(json.dumps(positions, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="Trade executor")
    sub = parser.add_subparsers(dest="command", required=True)

    p_open = sub.add_parser("open", help="Open a position")
    p_open.add_argument("--symbol", required=True, choices=SYMBOLS)
    p_open.add_argument("--side", required=True, choices=["BUY", "SELL"])
    p_open.add_argument("--size", required=True, type=float, help="USDT size (10-40)")
    p_open.add_argument("--tp", required=True, type=float, help="Take-profit %")
    p_open.add_argument("--sl", required=True, type=float, help="Stop-loss %")

    p_close = sub.add_parser("close", help="Close a position")
    p_close.add_argument("--symbol", required=True, choices=SYMBOLS)

    sub.add_parser("positions", help="List open positions")

    args = parser.parse_args()
    {"open": cmd_open, "close": cmd_close, "positions": cmd_positions}[args.command](args)


if __name__ == "__main__":
    main()
