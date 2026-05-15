_db = None


def _get_db():
    global _db
    if _db is None:
        from google.cloud import firestore as _firestore  # noqa: PLC0415

        _db = _firestore.Client()
    return _db


def _firestore():
    from google.cloud import firestore  # noqa: PLC0415

    return firestore


def get_position(symbol: str) -> dict | None:
    doc = _get_db().collection("positions").document(symbol).get()
    if doc.exists:
        return doc.to_dict()
    return None


def save_position(symbol: str, data: dict) -> None:
    _get_db().collection("positions").document(symbol).set(data, merge=True)


def clear_position(symbol: str) -> None:
    _get_db().collection("positions").document(symbol).delete()


def get_all_positions() -> list[dict]:
    docs = _get_db().collection("positions").stream()
    positions = []
    for doc in docs:
        entry = doc.to_dict()
        entry["symbol"] = doc.id
        positions.append(entry)
    return positions


def log_trade(event: dict) -> None:
    entry = dict(event)
    entry["timestamp"] = _firestore().SERVER_TIMESTAMP
    _get_db().collection("trade_log").add(entry)
