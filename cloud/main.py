import hmac
import json
import logging
import os
import threading
import traceback
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
TRADING_MODE = os.environ.get("TRADING_MODE", "testnet").lower()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Auto-trade gate — off by default, toggled via /auto-trade or Telegram /resume
AUTO_TRADE_ENABLED = os.environ.get("AUTO_TRADE_ENABLED", "false").lower() == "true"
AUTO_TRADE_MIN_SIGNALS = int(os.environ.get("AUTO_TRADE_MIN_SIGNALS", "5"))

_db = None
_auto_trade_lock = threading.Lock()
_auto_trade_active = AUTO_TRADE_ENABLED


def _get_db():
    global _db
    if _db is None:
        from google.cloud import firestore
        _db = firestore.Client()
    return _db


def _float(val):
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _store_alert(alert: dict) -> None:
    from google.cloud import firestore as fs
    alert["received_at"] = fs.SERVER_TIMESTAMP
    _get_db().collection("alerts").add(alert)


# ── Webhook ───────────────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        incoming = (
            request.headers.get("X-Webhook-Secret")
            or request.args.get("secret", "")
        )
        if not WEBHOOK_SECRET:
            logger.error("WEBHOOK_SECRET not configured")
            return jsonify({"error": "server misconfiguration"}), 401
        if not hmac.compare_digest(incoming, WEBHOOK_SECRET):
            logger.warning("Unauthorized webhook from %s", request.remote_addr)
            return jsonify({"error": "unauthorized"}), 401

        try:
            payload = json.loads(request.get_data(as_text=True))
        except json.JSONDecodeError as exc:
            return jsonify({"error": f"invalid JSON: {exc}"}), 400

        symbol = str(payload.get("symbol", "")).upper().strip()
        timeframe = str(payload.get("timeframe", "")).strip()
        if not symbol or not timeframe:
            return jsonify({"error": "symbol and timeframe required"}), 400

        alert = {
            "symbol": symbol,
            "timeframe": timeframe,
            "price":       _float(payload.get("price")),
            "ema20":       _float(payload.get("ema20")),
            "ema50":       _float(payload.get("ema50")),
            "rsi14":       _float(payload.get("rsi14")),
            "macd_hist":   _float(payload.get("macd_hist")),
            "atr14":       _float(payload.get("atr14")),
            "vol_ratio":   _float(payload.get("vol_ratio")),
            "stoch_rsi_k": _float(payload.get("stoch_rsi_k")),
            "adx":         _float(payload.get("adx")),
        }

        _store_alert(alert)
        logger.info("Alert stored: %s %s price=%.2f", symbol, timeframe, alert["price"] or 0)

        # Kick off auto-trade evaluation in background — webhook returns immediately
        if timeframe == "15" and _auto_trade_active:
            t = threading.Thread(target=_evaluate_and_trade, args=(symbol,), daemon=True)
            t.start()

        return jsonify({"status": "ok", "symbol": symbol, "timeframe": timeframe}), 200

    except Exception:
        logger.error("Error in /webhook:\n%s", traceback.format_exc())
        return jsonify({"error": "internal error"}), 500


def _check_tp_sl(symbol: str, position: dict, price: float) -> None:
    """Close a position if this bar's price crossed TP or SL (self-managed venues)."""
    if price <= 0:
        return
    from agent import broker, state
    from cloud import telegram

    tp = float(position.get("tp", 0))
    sl = float(position.get("sl", 0))
    side = position.get("side", "BUY")
    entry = float(position.get("entry_price", 0))
    qty = float(position.get("qty", 0))

    hit = None
    if side == "BUY":
        if tp and price >= tp:
            hit = "TP"
        elif sl and price <= sl:
            hit = "SL"
    else:  # SELL
        if tp and price <= tp:
            hit = "TP"
        elif sl and price >= sl:
            hit = "SL"
    if not hit:
        return

    broker.close_position(symbol)
    state.clear_position(symbol)
    pnl = (price - entry) * qty if side == "BUY" else (entry - price) * qty
    state.log_trade({"event": f"closed_{hit.lower()}", "symbol": symbol,
                     "side": side, "entry_price": entry, "exit_price": price,
                     "pnl": round(pnl, 4), "mode": TRADING_MODE})
    emoji = "✅" if hit == "TP" else "🔴"
    telegram.send(f"{emoji} <b>{symbol} {hit} hit</b> @ ${price:,.2f}\n"
                  f"PnL: ${pnl:+.2f}")
    logger.info("%s %s hit @ %s, pnl=%.4f", symbol, hit, price, pnl)

    if hit == "SL":
        cooldown_until = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        state.set_config(symbol, {"cooldown_until": cooldown_until})
        logger.info("Cooldown set for %s until %s", symbol, cooldown_until)


MAX_DAILY_LOSS_USDT = -20.0


def _evaluate_and_trade(symbol: str) -> None:
    """Runs in a background thread after each 15m bar is stored."""
    try:
        from agent import broker, risk, signals, state

        # Anti-whipsaw cooldown — skip if SL was hit recently on this symbol
        cfg = state.get_config(symbol) or {}
        cooldown_until = cfg.get("cooldown_until")
        if cooldown_until:
            try:
                until_dt = datetime.fromisoformat(cooldown_until)
                if datetime.now(timezone.utc) < until_dt:
                    logger.info("Cooldown active for %s until %s", symbol, cooldown_until)
                    return
            except ValueError:
                pass

        # Daily loss limit — pause auto-trading if today's realized losses exceed limit
        today_pnl = state.get_today_pnl()
        if today_pnl <= MAX_DAILY_LOSS_USDT:
            global _auto_trade_active
            with _auto_trade_lock:
                _auto_trade_active = False
            from cloud import telegram
            telegram.send(
                f"🛑 <b>Daily loss limit hit</b> (${today_pnl:.2f})\n"
                f"Auto-trading paused. Send /resume to restart."
            )
            logger.warning("Daily loss limit hit: $%.2f — auto-trade paused", today_pnl)
            return

        alerts_15m = state.get_recent_alerts(symbol, "15", 32)
        alerts_1h  = state.get_recent_alerts(symbol, "60", 8)
        position   = state.get_position(symbol)

        b = broker.active()

        # Self-managed TP/SL: for venues without native bracket orders, check
        # the open position against this bar's price before evaluating signals.
        if position and not b.manages_tp_sl_natively and alerts_15m:
            _check_tp_sl(symbol, position, float(alerts_15m[-1].get("price") or 0))
            position = state.get_position(symbol)  # may have been closed

        sig    = signals.evaluate(alerts_15m, alerts_1h, position)
        action = sig.get("action", "WAIT")

        if action not in ("OPEN_LONG", "OPEN_SHORT", "CLOSE"):
            return

        from cloud import telegram

        # Skip shorts on long-only venues (e.g. Alpaca crypto spot)
        if action == "OPEN_SHORT" and not b.supports_short:
            logger.info("%s OPEN_SHORT skipped — %s is long-only", symbol, b.name)
            return

        if action == "CLOSE" and position:
            broker.close_position(symbol)
            state.clear_position(symbol)
            reason = sig.get("reason", "signal reversal")
            state.log_trade({"event": "auto_closed", "symbol": symbol,
                             "reason": reason, "mode": TRADING_MODE})
            telegram.notify_closed(symbol, reason, TRADING_MODE)
            logger.info("AUTO CLOSE %s — %s", symbol, reason)
            return

        # Open trade
        side = "BUY" if action == "OPEN_LONG" else "SELL"
        score = sig.get("bull_signals" if side == "BUY" else "bear_signals", 0)
        if score < AUTO_TRADE_MIN_SIGNALS:
            logger.info("Signal %s %s score %d < min %d — skip", action, symbol,
                        score, AUTO_TRADE_MIN_SIGNALS)
            return

        if not alerts_15m:
            return
        price = float(alerts_15m[-1].get("price") or 0)
        if price == 0:
            return

        sl_pct    = sig["sl_pct"]
        tp1_pct   = sig.get("tp1_pct", sig["sl_pct"])
        tp2_pct   = sig.get("tp2_pct", round(sig["sl_pct"] * 2.0, 2))
        trail_pct = sig.get("trail_pct", round(sig["sl_pct"] * 0.5, 2))
        size_usdt = sig.get("size_usdt", 25.0)

        decision = {"action": action, "size_usdt": size_usdt,
                    "tp_pct": tp1_pct, "sl_pct": sl_pct}
        err = risk.validate_decision(symbol, decision, position)
        if err:
            logger.warning("Risk check blocked %s %s: %s", action, symbol, err)
            telegram.send(f"⚠️ <b>{symbol}</b> signal blocked by risk\n{err}")
            return

        size_usdt = float(decision["size_usdt"])
        qty = round(size_usdt / price, 3)
        if qty == 0:
            return

        if side == "BUY":
            tp1_price     = round(price * (1 + tp1_pct / 100), 2)
            tp2_price     = round(price * (1 + tp2_pct / 100), 2)
            sl_price      = round(price * (1 - sl_pct / 100), 2)
            trail_active  = round(price * (1 + tp1_pct * 1.5 / 100), 2)
        else:
            tp1_price     = round(price * (1 - tp1_pct / 100), 2)
            tp2_price     = round(price * (1 - tp2_pct / 100), 2)
            sl_price      = round(price * (1 + sl_pct / 100), 2)
            trail_active  = round(price * (1 - tp1_pct * 1.5 / 100), 2)
        trail_distance = round(price * trail_pct / 100, 2)

        order = broker.place_market_order(symbol, side, qty)
        pos_data = {
            "symbol": symbol, "side": side, "entry_price": price,
            "qty": qty, "tp": tp1_price, "tp2": tp2_price, "sl": sl_price,
            "size_usdt": size_usdt, "order_id": order.get("orderId"),
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "auto": True,
        }
        state.save_position(symbol, pos_data)
        if b.manages_tp_sl_natively:
            try:
                broker.set_tp_sl(symbol, side, qty, tp1_price, sl_price,
                                 tp2_price=tp2_price)
            except Exception as exc:
                logger.warning("set_tp_sl failed for %s: %s", symbol, exc)
            try:
                broker.set_trailing_stop(symbol, trail_distance,
                                         active_price=trail_active)
            except Exception as exc:
                logger.warning("set_trailing_stop failed for %s: %s", symbol, exc)
        state.log_trade({"event": "auto_opened", "mode": TRADING_MODE, **pos_data})

        telegram.notify_opened(symbol, side, price, tp1_price, sl_price,
                               size_usdt, score, 8, TRADING_MODE, tp2=tp2_price)
        logger.info("AUTO %s %s qty=%s entry=%s tp1=%s tp2=%s sl=%s trail=%s@%s",
                    side, symbol, qty, price, tp1_price, tp2_price, sl_price,
                    trail_distance, trail_active)

    except Exception:
        err = traceback.format_exc()
        logger.error("_evaluate_and_trade error for %s:\n%s", symbol, err)
        try:
            from cloud import telegram
            telegram.notify_error(f"auto-trade {symbol}", err)
        except Exception:
            pass


# ── Telegram bot command handler ──────────────────────────────────────────────

@app.route("/telegram-webhook", methods=["POST"])
def telegram_webhook():
    try:
        data = request.get_json(silent=True) or {}
        message = data.get("message", {})
        text = message.get("text", "").strip()
        chat_id = str(message.get("chat", {}).get("id", ""))

        if TELEGRAM_CHAT_ID and chat_id != TELEGRAM_CHAT_ID:
            return jsonify({"ok": True})

        from agent import broker, state
        from cloud import telegram

        if text == "/positions":
            positions = state.get_all_positions()
            if not positions:
                telegram.send("No open positions.")
            else:
                lines = []
                for p in positions:
                    lines.append(
                        f"<b>{p['symbol']} {p['side']}</b>\n"
                        f"Entry: ${float(p.get('entry_price',0)):,.2f}  "
                        f"TP: ${float(p.get('tp',0)):,.2f}  "
                        f"SL: ${float(p.get('sl',0)):,.2f}"
                    )
                telegram.send("\n\n".join(lines))

        elif text.startswith("/close "):
            sym = text.split()[1].upper()
            position = state.get_position(sym)
            if not position:
                telegram.send(f"No open position for {sym}")
            else:
                broker.close_position(sym)
                state.clear_position(sym)
                state.log_trade({"event": "telegram_closed", "symbol": sym})
                telegram.send(f"📤 Closed {sym}")

        elif text == "/pause":
            global _auto_trade_active
            with _auto_trade_lock:
                _auto_trade_active = False
            telegram.send("⏸ Auto-trading <b>paused</b>. Send /resume to restart.")

        elif text == "/resume":
            with _auto_trade_lock:
                _auto_trade_active = True
            telegram.send("▶️ Auto-trading <b>resumed</b>.")

        elif text == "/status":
            positions = state.get_all_positions()
            mode_tag = "🔴 LIVE" if TRADING_MODE == "live" else "🟡 TESTNET"
            auto_tag = "✅ ON" if _auto_trade_active else "⏸ PAUSED"
            telegram.send(
                f"<b>Bot status</b>\n"
                f"Mode: {mode_tag}\n"
                f"Auto-trade: {auto_tag}  (min signals: {AUTO_TRADE_MIN_SIGNALS}/6)\n"
                f"Open positions: {len(positions)}"
            )

        elif text == "/help":
            telegram.send(
                "<b>Commands</b>\n"
                "/positions — show open positions\n"
                "/close BTCUSDT — close a position\n"
                "/pause — disable auto-trading\n"
                "/resume — enable auto-trading\n"
                "/status — bot health + mode\n"
                "/help — this message"
            )

        return jsonify({"ok": True})
    except Exception:
        logger.error("telegram-webhook error:\n%s", traceback.format_exc())
        return jsonify({"ok": True})


# ── Reconcile ─────────────────────────────────────────────────────────────────

@app.route("/reconcile", methods=["GET"])
def reconcile():
    try:
        from agent import broker, state
        from cloud import telegram

        positions = state.get_all_positions()
        cleared = []
        for pos in positions:
            sym = pos.get("symbol")
            if not sym:
                continue
            try:
                if broker.get_open_position(sym) is None:
                    state.clear_position(sym)
                    cleared.append(sym)
                    logger.info("Reconcile: cleared ghost position %s", sym)
            except Exception as exc:
                logger.warning("Reconcile check failed for %s: %s", sym, exc)

        if cleared:
            telegram.send(f"🔄 Reconcile cleared ghost positions: {', '.join(cleared)}")
        return jsonify({"status": "ok", "cleared": cleared,
                        "checked": len(positions),
                        "timestamp": datetime.now(timezone.utc).isoformat()}), 200
    except Exception:
        logger.error("Error in /reconcile:\n%s", traceback.format_exc())
        return jsonify({"error": "internal error"}), 500


# ── Auto-trade toggle endpoints ───────────────────────────────────────────────

@app.route("/auto-trade/enable", methods=["POST"])
def enable_auto_trade():
    incoming = request.headers.get("X-Webhook-Secret") or request.args.get("secret", "")
    if not hmac.compare_digest(incoming, WEBHOOK_SECRET):
        return jsonify({"error": "unauthorized"}), 401
    global _auto_trade_active
    with _auto_trade_lock:
        _auto_trade_active = True
    logger.info("Auto-trade ENABLED via API")
    return jsonify({"auto_trade": True}), 200


@app.route("/auto-trade/disable", methods=["POST"])
def disable_auto_trade():
    incoming = request.headers.get("X-Webhook-Secret") or request.args.get("secret", "")
    if not hmac.compare_digest(incoming, WEBHOOK_SECRET):
        return jsonify({"error": "unauthorized"}), 401
    global _auto_trade_active
    with _auto_trade_lock:
        _auto_trade_active = False
    logger.info("Auto-trade DISABLED via API")
    return jsonify({"auto_trade": False}), 200


# ── State (positions + recent indicators) ────────────────────────────────────

@app.route("/state", methods=["GET"])
def state():
    """Returns open positions + last 32 alerts per symbol for Claude sessions."""
    try:
        from agent import state as s
        positions = s.get_all_positions()
        symbols = list({p["symbol"] for p in positions}) or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        alerts = {}
        for sym in symbols:
            alerts[sym] = {
                "15m": s.get_recent_alerts(sym, "15", 32),
                "1h":  s.get_recent_alerts(sym, "60", 8),
            }
        return jsonify({
            "positions": positions,
            "alerts": alerts,
            "mode": TRADING_MODE,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }), 200
    except Exception:
        logger.error("Error in /state:\n%s", traceback.format_exc())
        return jsonify({"error": "internal error"}), 500


@app.route("/indicators/<symbol>", methods=["GET"])
def indicators(symbol):
    """Returns last N bars of indicator data for a symbol."""
    try:
        from agent import state as s
        n = int(request.args.get("n", 32))
        tf = request.args.get("tf", "15")
        alerts = s.get_recent_alerts(symbol.upper(), tf, n)
        return jsonify({"symbol": symbol.upper(), "timeframe": tf, "bars": alerts}), 200
    except Exception:
        logger.error("Error in /indicators:\n%s", traceback.format_exc())
        return jsonify({"error": "internal error"}), 500


# ── Daily P&L summary ─────────────────────────────────────────────────────────

@app.route("/daily-summary", methods=["GET"])
def daily_summary():
    try:
        from agent import state as s
        from cloud import telegram

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        resp = __import__("requests").get(
            "https://firestore.googleapis.com/v1/projects/tradingbot-496815"
            "/databases/(default)/documents/trade_log",
            headers=s._headers(), timeout=15,
        )
        resp.raise_for_status()

        trades, wins, losses, total_pnl = 0, 0, 0, 0.0
        for doc in resp.json().get("documents", []):
            fields = s._dec_fields(doc.get("fields", {}))
            ts = str(fields.get("timestamp", ""))
            if not ts.startswith(today):
                continue
            event = fields.get("event", "")
            if "opened" in event:
                continue
            trades += 1
            pnl = float(fields.get("pnl") or 0)
            total_pnl += pnl
            if pnl >= 0:
                wins += 1
            else:
                losses += 1

        positions = s.get_all_positions()
        open_syms = ", ".join(p["symbol"] for p in positions) or "none"
        win_rate = f"{wins / trades * 100:.0f}%" if trades else "N/A"

        msg = (
            f"📊 <b>Daily — {today}</b>\n"
            f"Trades: {trades} | Won: {wins} | Lost: {losses}\n"
            f"Realized P&L: ${total_pnl:+.2f} | Win rate: {win_rate}\n"
            f"Open positions: {open_syms}"
        )
        telegram.send(msg)
        return jsonify({"status": "ok", "date": today, "trades": trades,
                        "pnl": round(total_pnl, 2), "wins": wins, "losses": losses}), 200
    except Exception:
        logger.error("Error in /daily-summary:\n%s", traceback.format_exc())
        return jsonify({"error": "internal error"}), 500



# ── /pnl — multi-day performance stats ───────────────────────────────────────

@app.route("/pnl", methods=["GET"])
def pnl_stats():
    try:
        days = max(1, int(request.args.get("days", 7)))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        from agent import state as s
        resp = __import__("requests").get(
            "https://firestore.googleapis.com/v1/projects/tradingbot-496815"
            "/databases/(default)/documents/trade_log",
            headers=s._headers(), timeout=20,
        )
        resp.raise_for_status()

        trades, wins, losses, total_pnl = 0, 0, 0, 0.0
        win_pnl, loss_pnl = 0.0, 0.0
        by_symbol: dict = {}

        for doc in resp.json().get("documents", []):
            fields = s._dec_fields(doc.get("fields", {}))
            ts = str(fields.get("timestamp", ""))
            if ts < cutoff:
                continue
            event = fields.get("event", "")
            if "opened" in event:
                continue
            pnl = fields.get("pnl")
            if pnl is None:
                continue
            pnl = float(pnl)
            sym = str(fields.get("symbol", "?"))
            trades += 1
            total_pnl += pnl
            if pnl > 0:
                wins += 1
                win_pnl += pnl
            else:
                losses += 1
                loss_pnl += pnl
            if sym not in by_symbol:
                by_symbol[sym] = {"pnl": 0.0, "trades": 0, "wins": 0}
            by_symbol[sym]["pnl"] = round(by_symbol[sym]["pnl"] + pnl, 4)
            by_symbol[sym]["trades"] += 1
            if pnl > 0:
                by_symbol[sym]["wins"] += 1

        win_rate = round(wins / trades * 100, 1) if trades else 0
        avg_win  = round(win_pnl / wins, 4) if wins else 0
        avg_loss = round(loss_pnl / losses, 4) if losses else 0
        rr = round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else None

        return jsonify({
            "days": days,
            "trades": trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "realized": round(total_pnl, 2),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_rr": rr,
            "by_symbol": by_symbol,
        }), 200
    except Exception:
        logger.error("Error in /pnl:\n%s", traceback.format_exc())
        return jsonify({"error": "internal error"}), 500


# ── Health ────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "mode": TRADING_MODE,
        "auto_trade": _auto_trade_active,
        "min_signals": AUTO_TRADE_MIN_SIGNALS,
        "role": "auto-executor",
    }), 200
