"""
Rule-based signal engine — 6-point indicator consensus.

Improvements over v1:
- MACD acceleration (positive AND growing, not just positive)
- EMA20 slope filter (upward sloping, not just above EMA50)
- RSI signals split: zone check + not-extreme are now distinct
- Dynamic ATR-based position sizing scaled by signal confidence
"""

from agent.config import MAX_SL_PCT, MIN_TP_SL_RATIO, MAX_SIZE_USDT


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
    p15 = alerts_15m[-2] if len(alerts_15m) >= 2 else {}  # previous bar
    l1h = alerts_1h[-1] if alerts_1h else {}

    price     = _safe(l15.get("price"), 1.0)
    ema20_15  = _safe(l15.get("ema20"))
    ema50_15  = _safe(l15.get("ema50"))
    ema20_1h  = _safe(l1h.get("ema20"))
    ema50_1h  = _safe(l1h.get("ema50"))
    rsi       = _safe(l15.get("rsi14"), 50.0)
    macd      = _safe(l15.get("macd_hist"))
    prev_macd = _safe(p15.get("macd_hist"))
    prev_ema20 = _safe(p15.get("ema20"))
    vol       = _safe(l15.get("vol_ratio"), 1.0)
    atr       = _safe(l15.get("atr14"))

    trend_15m = ema20_15 > ema50_15 if ema20_15 and ema50_15 else None
    trend_1h  = ema20_1h > ema50_1h if ema20_1h and ema50_1h else None
    ema20_sloping_up   = ema20_15 > prev_ema20 if ema20_15 and prev_ema20 else None
    ema20_sloping_down = ema20_15 < prev_ema20 if ema20_15 and prev_ema20 else None
    macd_accel = macd > prev_macd   # histogram growing
    macd_decel = macd < prev_macd   # histogram shrinking

    # ── Bullish signals (each +1, max 6) ──────────────────────────────────────
    bull = [
        trend_15m is True,                  # 1. EMA20 above EMA50 on 15m
        trend_1h is True,                   # 2. EMA20 above EMA50 on 1h
        50 < rsi < 72,                      # 3. RSI positive zone, not overbought
        macd > 0 and macd_accel,            # 4. MACD positive AND accelerating
        vol > 1.2,                          # 5. Above-average volume
        ema20_sloping_up is True,           # 6. EMA20 sloping upward (momentum)
    ]

    # ── Bearish signals (each +1, max 6) ──────────────────────────────────────
    bear = [
        trend_15m is False,                 # 1. EMA20 below EMA50 on 15m
        trend_1h is False,                  # 2. EMA20 below EMA50 on 1h
        28 < rsi < 50,                      # 3. RSI negative zone, not oversold
        macd < 0 and macd_decel,            # 4. MACD negative AND worsening
        vol > 1.2,                          # 5. Above-average volume
        ema20_sloping_down is True,         # 6. EMA20 sloping downward
    ]

    bull_count = sum(bull)
    bear_count = sum(bear)

    # ── ATR-based TP/SL ───────────────────────────────────────────────────────
    sl_pct = round((atr / price) * 100, 2) if price > 0 and atr > 0 else 0.5
    sl_pct = min(sl_pct, MAX_SL_PCT)
    sl_pct = max(sl_pct, 0.2)
    tp_pct = round(sl_pct * MIN_TP_SL_RATIO, 2)

    # ── Dynamic position sizing — scales with signal confidence ───────────────
    def _dynamic_size(score: int) -> float:
        confidence = score / 6.0           # 0.67 → 1.0 for scores 4-6
        base = MAX_SIZE_USDT * 0.5         # $20 base
        extra = MAX_SIZE_USDT * 0.5        # up to $20 extra at max confidence
        size = base + (extra * (confidence - 0.5) / 0.5)
        return round(max(15.0, min(MAX_SIZE_USDT, size)), 1)

    meta = {
        "bull_signals":   bull_count,
        "bear_signals":   bear_count,
        "rsi":            rsi,
        "macd_hist":      macd,
        "vol_ratio":      vol,
        "ema_trend_15m":  "bull" if trend_15m else ("bear" if trend_15m is False else "unknown"),
        "ema_trend_1h":   "bull" if trend_1h  else ("bear" if trend_1h  is False else "unknown"),
        "sl_pct":         sl_pct,
        "tp_pct":         tp_pct,
    }

    if position is None:
        if bull_count >= 4:
            return {"action": "OPEN_LONG",
                    "size_usdt": _dynamic_size(bull_count),
                    "sl_pct": sl_pct, "tp_pct": tp_pct, **meta}
        if bear_count >= 4:
            return {"action": "OPEN_SHORT",
                    "size_usdt": _dynamic_size(bear_count),
                    "sl_pct": sl_pct, "tp_pct": tp_pct, **meta}
        return {"action": "WAIT", **meta}

    side = position.get("side", "")
    if side == "BUY" and bear_count >= 3:
        return {"action": "CLOSE",
                "reason": f"{bear_count}/6 bearish signals vs open LONG", **meta}
    if side == "SELL" and bull_count >= 3:
        return {"action": "CLOSE",
                "reason": f"{bull_count}/6 bullish signals vs open SHORT", **meta}
    return {"action": "HOLD", **meta}
