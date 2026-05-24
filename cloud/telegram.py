import logging
import os

import requests as _requests

logger = logging.getLogger(__name__)

_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send(text: str) -> None:
    if not _TOKEN or not _CHAT_ID:
        logger.info("Telegram not configured — msg: %s", text[:120])
        return
    try:
        _requests.post(
            f"https://api.telegram.org/bot{_TOKEN}/sendMessage",
            json={"chat_id": _CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=6,
        )
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)


def notify_opened(symbol: str, side: str, price: float, tp: float, sl: float,
                  size: float, score: int, total: int, mode: str,
                  tp2: float | None = None) -> None:
    emoji = "🟢" if side == "BUY" else "🔴"
    direction = "LONG" if side == "BUY" else "SHORT"
    mode_tag = "⚠️ LIVE" if mode == "live" else "🟡 TESTNET"
    tp_line = f"TP1: ${tp:,.2f}  TP2: ${tp2:,.2f}  SL: ${sl:,.2f}" if tp2 else \
              f"TP: ${tp:,.2f}    SL: ${sl:,.2f}"
    send(
        f"{emoji} <b>AUTO {direction} — {symbol}</b>  [{mode_tag}]\n"
        f"Entry: <b>${price:,.2f}</b>\n"
        f"{tp_line}\n"
        f"Size: ${size:.0f}    Signal: {score}/{total}"
    )


def notify_closed(symbol: str, reason: str, mode: str) -> None:
    mode_tag = "⚠️ LIVE" if mode == "live" else "🟡 TESTNET"
    send(f"📤 <b>AUTO CLOSE — {symbol}</b>  [{mode_tag}]\n{reason}")


def notify_signal(symbol: str, action: str, bull: int, bear: int,
                  rsi: float, vol: float) -> None:
    send(
        f"📡 <b>Signal: {action} — {symbol}</b>\n"
        f"Bull: {bull}/6    Bear: {bear}/6\n"
        f"RSI: {rsi:.1f}    Vol: {vol:.2f}×"
    )


def notify_error(context: str, error: str) -> None:
    send(f"🚨 <b>Error in {context}</b>\n<code>{error[:300]}</code>")
