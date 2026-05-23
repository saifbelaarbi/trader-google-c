import hmac
import json
import logging
import os
import threading
import traceback
from datetime import datetime, timezone

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
            "price":      _float(payload.get("price")),
            "ema20":      _float(payload.get("ema20")),
            "ema50":      _float(payload.get("ema50")),
            "rsi14":      _float(payload.get("rsi14")),
            "macd_hist":  _float(payload.get("macd_hist")),
            "atr14":      _float(payload.get("atr14")),
            "vol_ratio":  _float(payload.get("vol_ratio")),
        }

        from google.cloud import firestore as fs
        alert["received_at"] = fs.SERVER_TIMESTAMP
        _get_db().collection("alerts").add(alert)
        logger.info("Alert stored: %s %s price=%.2f", symbol, timeframe, alert["price"] or 0)

        # Kick off auto-trade evaluation in background — webhook returns immediately
        if timeframe == "15" and _auto_trade_active:
            t = threading.Thread(target=_evaluate_and_trade, args=(symbol,), daemon=True)
            t.start()

        return jsonify({"status": "ok", "symbol": symbol, "timeframe": timeframe}), 200

    except Exception:
        logger.error("Error in /webhook:\n%s", traceback.format_exc())
        return jsonify({"error": "internal error"}), 500


def _evaluate_and_trade(symbol: str) -> None:
    """Runs in a background thread after each 15m bar is stored."""
    try:
        from agent import broker, risk, signals, state

        alerts_15m = state.get_recent_alerts(symbol, "15", 32)
        alerts_1h  = state.get_recent_alerts(symbol, "60", 8)
        position   = state.get_position(symbol)

        sig    = signals.evaluate(alerts_15m, alerts_1h, position)
        action = sig.get("action", "WAIT")

        if action not in ("OPEN_LONG", "OPEN_SHORT", "CLOSE"):
            return

        from cloud import telegram

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

        sl_pct   = sig["sl_pct"]
        tp_pct   = sig["tp_pct"]
        size_usdt = sig.get("size_usdt", 25.0)

        decision = {"action": action, "size_usdt": size_usdt,
                    "tp_pct": tp_pct, "sl_pct": sl_pct}
        err = risk.validate_decision(symbol, decision, position)
        if err:
            logger.warning("Risk check blocked %s %s: %s", action, symbol, err)
            telegram.send(f"⚠️ <b>{symbol}</b> signal blocked by risk\n{err}")
            return

        size_usdt = float(decision["size_usdt"])
        qty = round(size_usdt / price, 3)
        if qty == 0:
            return

        tp_price = round(price * (1 + tp_pct / 100), 2) if side == "BUY" \
                   else round(price * (1 - tp_pct / 100), 2)
        sl_price = round(price * (1 - sl_pct / 100), 2) if side == "BUY" \
                   else round(price * (1 + sl_pct / 100), 2)

        order = broker.place_market_order(symbol, side, qty)
        pos_data = {
            "symbol": symbol, "side": side, "entry_price": price,
            "qty": qty, "tp": tp_price, "sl": sl_price,
            "size_usdt": size_usdt, "order_id": order.get("orderId"),
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "auto": True,
        }
        state.save_position(symbol, pos_data)
        try:
            broker.set_tp_sl(symbol, side, qty, tp_price, sl_price)
        except Exception as exc:
            logger.warning("set_tp_sl failed for %s: %s", symbol, exc)
        state.log_trade({"event": "auto_opened", "mode": TRADING_MODE, **pos_data})

        telegram.notify_opened(symbol, side, price, tp_price, sl_price,
                               size_usdt, score, 6, TRADING_MODE)
        logger.info("AUTO %s %s qty=%s entry=%s tp=%s sl=%s",
                    side, symbol, qty, price, tp_price, sl_price)

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
                binance_positions = broker._get_client().futures_position_information(symbol=sym)
                open_pos = next((p for p in binance_positions
                                 if float(p["positionAmt"]) != 0), None)
                if open_pos is None:
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
