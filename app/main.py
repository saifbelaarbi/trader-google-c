import hmac
import json
import logging
import os
import traceback
from datetime import datetime, timezone

from flask import Flask, jsonify, request

from app import reconcile, state, trade_engine
from app.risk import validate_signal

app = Flask(__name__)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ):
                log_entry[key] = value
        return json.dumps(log_entry)


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    app.logger.handlers = []
    app.logger.propagate = True


_setup_logging()
logger = app.logger

TRADING_MODE = os.environ.get("TRADING_MODE", "testnet")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        raw_body = request.get_data(as_text=True)
        incoming_secret = request.headers.get("X-Webhook-Secret", "")

        if not hmac.compare_digest(incoming_secret, WEBHOOK_SECRET):
            logger.warning("Unauthorized webhook attempt from %s", request.remote_addr)
            return jsonify({"error": "unauthorized"}), 401

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as e:
            return jsonify({"error": f"invalid JSON: {e}"}), 400

        logger.info(
            "Incoming webhook",
            extra={
                "symbol": payload.get("symbol"),
                "action": payload.get("action"),
                "source_ip": request.remote_addr,
            },
        )

        try:
            validate_signal(payload)
        except ValueError as e:
            logger.warning("Signal rejected: %s", str(e))
            return jsonify({"error": str(e)}), 400

        result = trade_engine.handle_signal(payload)
        return jsonify(result), 200

    except Exception:
        logger.error("Unhandled exception in /webhook: %s", traceback.format_exc())
        return jsonify({"error": "internal error"}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "mode": TRADING_MODE}), 200


@app.route("/reconcile", methods=["GET"])
def reconcile_route():
    try:
        result = reconcile.run_reconciliation()
        return jsonify(result), 200
    except Exception:
        logger.error("Unhandled exception in /reconcile: %s", traceback.format_exc())
        return jsonify({"error": "internal error"}), 500


@app.route("/positions", methods=["GET"])
def positions():
    try:
        all_positions = state.get_all_positions()
        return jsonify(all_positions), 200
    except Exception:
        logger.error("Unhandled exception in /positions: %s", traceback.format_exc())
        return jsonify({"error": "internal error"}), 500
