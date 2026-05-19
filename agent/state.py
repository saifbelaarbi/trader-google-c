import logging

logger = logging.getLogger(__name__)

_db = None


def _get_db():
    global _db
    if _db is None:
        from google.cloud import firestore

        _db = firestore.Client()
    return _db


def get_recent_alerts(symbol: str, timeframe: str, limit: int) -> list[dict]:
    """Return the last `limit` alerts for symbol+timeframe in chronological order."""
    from google.cloud import firestore

    docs = (
        _get_db()
        .collection("alerts")
        .where("symbol", "==", symbol)
        .where("timeframe", "==", timeframe)
        .order_by("received_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    results = [doc.to_dict() for doc in docs]
    results.reverse()
    return results


def get_latest_alert(symbol: str, timeframe: str) -> dict | None:
    alerts = get_recent_alerts(symbol, timeframe, limit=1)
    return alerts[0] if alerts else None


def get_position(symbol: str) -> dict | None:
    doc = _get_db().collection("positions").document(symbol).get()
    return doc.to_dict() if doc.exists else None


def get_all_positions() -> list[dict]:
    docs = _get_db().collection("positions").stream()
    return [{"symbol": doc.id, **doc.to_dict()} for doc in docs]


def save_position(symbol: str, data: dict) -> None:
    _get_db().collection("positions").document(symbol).set(data)


def clear_position(symbol: str) -> None:
    _get_db().collection("positions").document(symbol).delete()


def log_trade(event: dict) -> None:
    from google.cloud import firestore

    entry = {**event, "timestamp": firestore.SERVER_TIMESTAMP}
    _get_db().collection("trade_log").add(entry)


def log_decision(symbol: str, decision: dict) -> None:
    from google.cloud import firestore

    entry = {"symbol": symbol, **decision, "timestamp": firestore.SERVER_TIMESTAMP}
    _get_db().collection("decisions").add(entry)
