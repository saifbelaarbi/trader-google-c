"""
Rule-based signal engine.

Evaluates the last 8 hours of indicator history and returns a signal dict.
No external API calls — pure Python rules.

Signal strength is a count of agreeing indicators (max 6):
  EMA15m trend | EMA1h trend | RSI zone | MACD hist direction | volume | RSI not extreme
A trade fires only when ≥ 4 out of 6 indicators agree.
"""

from agent.config import MAX_SL_PCT, MIN_TP_SL_RATIO


def _safe(val, default=0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def evaluate(
    alerts_15m: list[dict],
    alerts_1h: list[dict],
    position: dict | None,
) -> dict:
    if not alerts_15m:
        return {"action": "WAIT", "reason": "No 15m data in Firestore"}

    l15 = alerts_15m[-1]
    l1h = alerts_1h[-1] if alerts_1h else {}

    price = _safe(l15.get("price"), 1.0)
    ema20_15 = _safe(l15.get("ema20"))
    ema50_15 = _safe(l15.get("ema50"))
    ema20_1h = _safe(l1h.get("ema20"))
    ema50_1h = _safe(l1h.get("ema50"))
    rsi = _safe(l15.get("rsi14"), 50.0)
    macd = _safe(l15.get("macd_hist"))
    vol = _safe(l15.get("vol_ratio"), 1.0)
    atr = _safe(l15.get("atr14"))

    trend_15m = ema20_15 > ema50_15 if ema20_15 and ema50_15 else None
    trend_1h = ema20_1h > ema50_1h if ema20_1h and ema50_1h else None

    # Bullish signals (each adds 1)
    bull = [
        trend_15m is True,
        trend_1h is True,
        50 < rsi < 70,     # positive momentum, not overbought
        macd > 0,
        vol > 1.2,         # above-average volume
        rsi < 65,          # not in extreme zone
    ]

    # Bearish signals (each adds 1)
    bear = [
        trend_15m is False,
        trend_1h is False,
        30 < rsi < 50,     # negative momentum, not oversold
        macd < 0,
        vol > 1.2,
        rsi > 35,
    ]

    bull_count = sum(bull)
    bear_count = sum(bear)

    # ATR-based TP/SL sizing
    sl_pct = round((atr / price) * 100, 2) if price > 0 and atr > 0 else 0.5
    sl_pct = min(sl_pct, MAX_SL_PCT)
    sl_pct = max(sl_pct, 0.2)
    tp_pct = round(sl_pct * MIN_TP_SL_RATIO, 2)

    meta = {
        "bull_signals": bull_count,
        "bear_signals": bear_count,
        "rsi": rsi,
        "macd_hist": macd,
        "vol_ratio": vol,
        "ema_trend_15m": "bull" if trend_15m else ("bear" if trend_15m is False else "unknown"),
        "ema_trend_1h": "bull" if trend_1h else ("bear" if trend_1h is False else "unknown"),
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
    }

    if position is None:
        if bull_count >= 4:
            return {"action": "OPEN_LONG", "size_usdt": 30.0, "sl_pct": sl_pct, "tp_pct": tp_pct, **meta}
        if bear_count >= 4:
            return {"action": "OPEN_SHORT", "size_usdt": 30.0, "sl_pct": sl_pct, "tp_pct": tp_pct, **meta}
        return {"action": "WAIT", **meta}

    side = position.get("side", "")
    if side == "BUY" and bear_count >= 3:
        return {"action": "CLOSE", "reason": f"{bear_count} bearish signals vs open LONG", **meta}
    if side == "SELL" and bull_count >= 3:
        return {"action": "CLOSE", "reason": f"{bull_count} bullish signals vs open SHORT", **meta}
    return {"action": "HOLD", **meta}
