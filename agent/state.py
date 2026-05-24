"""Firestore state layer — uses REST API so it works in gRPC-blocked environments."""
import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

PROJECT = "tradingbot-496815"
_BASE = (
    f"https://firestore.googleapis.com/v1/projects/{PROJECT}"
    "/databases/(default)/documents"
)
_creds = None


def _headers() -> dict:
    global _creds
    import google.auth
    import google.auth.transport.requests

    if _creds is None:
        _creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/datastore"]
        )
    _creds.refresh(google.auth.transport.requests.Request())
    return {"Authorization": f"Bearer {_creds.token}", "Content-Type": "application/json"}


# ── Firestore value codec ─────────────────────────────────────────────────────

def _dec(v: dict):
    if "stringValue" in v:
        return v["stringValue"]
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "integerValue" in v:
        return int(v["integerValue"])
    if "booleanValue" in v:
        return v["booleanValue"]
    if "timestampValue" in v:
        return v["timestampValue"]
    if "mapValue" in v:
        return _dec_fields(v["mapValue"].get("fields", {}))
    return None


def _dec_fields(fields: dict) -> dict:
    return {k: _dec(v) for k, v in fields.items()}


def _enc(v) -> dict:
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: _enc(u) for k, u in v.items()}}}
    return {"stringValue": str(v)}


def _enc_fields(data: dict) -> dict:
    return {k: _enc(v) for k, v in data.items()}


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _query(
    collection: str,
    filters: list[dict],
    order_by: str | None = None,
    direction: str = "DESCENDING",
    limit: int | None = None,
) -> list[dict]:
    body: dict = {
        "structuredQuery": {
            "from": [{"collectionId": collection}],
            "where": {"compositeFilter": {"op": "AND", "filters": filters}},
        }
    }
    if order_by:
        body["structuredQuery"]["orderBy"] = [
            {"field": {"fieldPath": order_by}, "direction": direction}
        ]
    if limit:
        body["structuredQuery"]["limit"] = limit

    resp = requests.post(
        f"{_BASE}:runQuery", headers=_headers(), json=body, timeout=15
    )
    resp.raise_for_status()
    return [
        _dec_fields(item["document"].get("fields", {}))
        for item in resp.json()
        if "document" in item
    ]


def _get_doc(collection: str, doc_id: str) -> dict | None:
    resp = requests.get(
        f"{_BASE}/{collection}/{doc_id}", headers=_headers(), timeout=10
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return _dec_fields(resp.json().get("fields", {}))


def _set_doc(collection: str, doc_id: str, data: dict) -> None:
    resp = requests.patch(
        f"{_BASE}/{collection}/{doc_id}",
        headers=_headers(),
        json={"fields": _enc_fields(data)},
        timeout=10,
    )
    resp.raise_for_status()


def _delete_doc(collection: str, doc_id: str) -> None:
    resp = requests.delete(
        f"{_BASE}/{collection}/{doc_id}", headers=_headers(), timeout=10
    )
    resp.raise_for_status()


def _add_doc(collection: str, data: dict) -> None:
    resp = requests.post(
        f"{_BASE}/{collection}",
        headers=_headers(),
        json={"fields": _enc_fields(data)},
        timeout=10,
    )
    resp.raise_for_status()


def _list_docs(collection: str) -> list[dict]:
    resp = requests.get(f"{_BASE}/{collection}", headers=_headers(), timeout=10)
    resp.raise_for_status()
    docs = []
    for doc in resp.json().get("documents", []):
        name = doc["name"].split("/")[-1]
        docs.append({"symbol": name, **_dec_fields(doc.get("fields", {}))})
    return docs


# ── Public API ────────────────────────────────────────────────────────────────

def get_recent_alerts(symbol: str, timeframe: str, limit: int) -> list[dict]:
    filters = [
        {"fieldFilter": {
            "field": {"fieldPath": "symbol"}, "op": "EQUAL", "value": _enc(symbol),
        }},
        {"fieldFilter": {
            "field": {"fieldPath": "timeframe"}, "op": "EQUAL", "value": _enc(timeframe),
        }},
    ]
    results = _query(
        "alerts", filters, order_by="received_at", direction="DESCENDING", limit=limit
    )
    results.reverse()
    return results


def get_latest_alert(symbol: str, timeframe: str) -> dict | None:
    alerts = get_recent_alerts(symbol, timeframe, limit=1)
    return alerts[0] if alerts else None


def get_position(symbol: str) -> dict | None:
    return _get_doc("positions", symbol)


def get_all_positions() -> list[dict]:
    return _list_docs("positions")


def save_position(symbol: str, data: dict) -> None:
    _set_doc("positions", symbol, data)


def clear_position(symbol: str) -> None:
    _delete_doc("positions", symbol)


def log_trade(event: dict) -> None:
    entry = {**event, "timestamp": datetime.now(timezone.utc).isoformat()}
    _add_doc("trade_log", entry)


def log_decision(symbol: str, decision: dict) -> None:
    entry = {
        "symbol": symbol,
        **decision,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _add_doc("decisions", entry)
