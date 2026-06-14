"""
Read the paper-trading Freqtrade bot's live telemetry from Firestore.

The bot (ClaudeBreakout on the user's PC) POSTs entry/exit fills and per-candle
status to the Cloud Run relay, which writes them to Firestore (collections
`ft_status` and `ft_events`). This lets a cloud Claude session check live bot
state without reaching the PC.

Requires GCP credentials in the environment (google.auth.default). If absent,
this prints a clear setup hint rather than a stack trace.

Usage:
    python -m agent.ft_monitor            # latest snapshot + recent events
    python -m agent.ft_monitor --events 50
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except ImportError:
        pass

import requests as _requests

from agent import state


def _fetch_events(limit: int) -> list[dict]:
    resp = _requests.get(
        f"{state._BASE}/ft_events",
        headers=state._headers(),
        params={"pageSize": limit, "orderBy": "received_at desc"},
        timeout=20,
    )
    resp.raise_for_status()
    out = []
    for doc in resp.json().get("documents", []):
        out.append(state._dec_fields(doc.get("fields", {})))
    return out


def _fetch_latest() -> dict | None:
    doc = state._get_doc("ft_status", "latest")
    return doc


def monitor(events: int = 20) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'=' * 62}")
    print(f"  FREQTRADE LIVE TELEMETRY  ({now})")
    print(f"{'=' * 62}")

    try:
        latest = _fetch_latest()
        recent = _fetch_events(events)
    except Exception as exc:
        msg = str(exc)
        print("\n  Could not read Firestore telemetry.")
        if "default credentials" in msg.lower() or "could not automatically" in msg.lower():
            print("  → No GCP credentials in this environment.")
            print("    Set GOOGLE_APPLICATION_CREDENTIALS to a Firestore-readable")
            print("    service-account key, then retry.")
        else:
            print(f"  → {msg}")
        print(f"\n{'=' * 62}\n")
        return

    if not latest and not recent:
        print("\n  No telemetry yet. Confirm the bot's webhook is enabled and")
        print("  pointing at the relay /ft-event endpoint.\n")
        print(f"{'=' * 62}\n")
        return

    if latest:
        print("\n  Latest event:")
        for k, v in latest.items():
            if k == "received_at":
                continue
            print(f"    {k:<14}: {v}")

    if recent:
        print(f"\n  Recent events ({len(recent)}):")
        for ev in recent:
            etype = str(ev.get("type", "?"))
            pair = str(ev.get("pair", ""))
            extra = ev.get("status") or ev.get("exit_reason") or ev.get("enter_tag") or ""
            pnl = ev.get("profit_amount")
            pnl_str = f"  P&L ${float(pnl):+.2f}" if pnl is not None else ""
            print(f"    {etype:<12} {pair:<16} {str(extra)[:40]}{pnl_str}")

    print(f"\n{'=' * 62}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read Freqtrade live telemetry from Firestore")
    parser.add_argument("--events", type=int, default=20, help="How many recent events to show")
    args = parser.parse_args()
    monitor(args.events)
