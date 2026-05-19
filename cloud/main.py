import hmac
import json
import logging
import os
import traceback

from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

_db = None


def _get_db():
    global _db
    if _db is None:
        from google.cloud import firestore

        _db = firestore.Client()
    return _db


def _store_alert(alert: dict) -> None:
    from google.cloud import firestore as fs

    alert["received_at"] = fs.SERVER_TIMESTAMP
    _get_db().collection("alerts").add(alert)


def _float(val) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        incoming_secret = request.headers.get("X-Webhook-Secret", "")

        if not WEBHOOK_SECRET:
            logger.error("WEBHOOK_SECRET not configured — rejecting request")
            return jsonify({"error": "server misconfiguration"}), 401

        if not hmac.compare_digest(incoming_secret, WEBHOOK_SECRET):
            logger.warning("Unauthorized webhook attempt from %s", request.remote_addr)
            return jsonify({"error": "unauthorized"}), 401

        try:
            payload = json.loads(request.get_data(as_text=True))
        except json.JSONDecodeError as e:
            return jsonify({"error": f"invalid JSON: {e}"}), 400

        symbol = str(payload.get("symbol", "")).upper().strip()
        timeframe = str(payload.get("timeframe", "")).strip()
        if not symbol or not timeframe:
            return jsonify({"error": "symbol and timeframe required"}), 400

        alert = {
            "symbol": symbol,
            "timeframe": timeframe,
            "price": _float(payload.get("price")),
            "ema20": _float(payload.get("ema20")),
            "ema50": _float(payload.get("ema50")),
            "rsi14": _float(payload.get("rsi14")),
            "macd_hist": _float(payload.get("macd_hist")),
            "atr14": _float(payload.get("atr14")),
            "vol_ratio": _float(payload.get("vol_ratio")),
        }

        _store_alert(alert)
        logger.info("Alert stored: %s %s price=%.2f", symbol, timeframe, alert["price"] or 0)
        return jsonify({"status": "ok", "symbol": symbol, "timeframe": timeframe}), 200

    except Exception:
        logger.error("Error in /webhook: %s", traceback.format_exc())
        return jsonify({"error": "internal error"}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "role": "relay"}), 200
