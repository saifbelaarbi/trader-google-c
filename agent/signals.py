"""
Rule-based signal engine — 8-point indicator consensus.

Points:
  1. EMA20 > EMA50 on 15m (trend)
  2. EMA20 > EMA50 on 1h (higher-tf trend)
  3. RSI in bull/bear zone
  4. MACD histogram positive/negative AND accelerating
  5. Volume ratio > 1.2
  6. EMA20 slope direction
  7. StochRSI K rising from low / falling from high
  8. ADX > 25 (trending market)

Market regime (M4): ATR/EMA50 ratio on 1h.
  > 0.015 → trending   → normal thresholds + full size
  < 0.008 → ranging    → +1 signal required, size reduced 40%
"""

from agent.config import MAX_SIZE_USDT


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
    p15 = alerts_15m[-2] if len(alerts_15m) >= 2 else {}
    l1h = alerts_1h[-1] if alerts_1h else {}

    price      = _safe(l15.get("price"), 1.0)
    ema20_15   = _safe(l15.get("ema20"))
    ema50_15   = _safe(l15.get("ema50"))
    ema20_1h   = _safe(l1h.get("ema20"))
    ema50_1h   = _safe(l1h.get("ema50"))
    atr_1h     = _safe(l1h.get("atr14"))
    rsi        = _safe(l15.get("rsi14"), 50.0)
    macd       = _safe(l15.get("macd_hist"))
    prev_macd  = _safe(p15.get("macd_hist"))
    prev_ema20 = _safe(p15.get("ema20"))
    vol        = _safe(l15.get("vol_ratio"), 1.0)
    atr        = _safe(l15.get("atr14"))
    stoch_rsi  = _safe(l15.get("stoch_rsi_k"), 50.0)
    prev_stoch = _safe(p15.get("stoch_rsi_k"), 50.0)
    adx        = _safe(l15.get("adx"), 0.0)

    # ── Market regime (M4) — ATR/EMA50 ratio on 1h ───────────────────────────
    regime = "unknown"
    size_regime_factor = 1.0
    if ema50_1h > 0 and atr_1h > 0:
        ratio = atr_1h / ema50_1h
        if ratio > 0.015:
            regime = "trending"
        elif ratio < 0.008:
            regime = "ranging"
            size_regime_factor = 0.6

    trend_15m          = ema20_15 > ema50_15 if ema20_15 and ema50_15 else None
    trend_1h           = ema20_1h > ema50_1h if ema20_1h and ema50_1h else None
    ema20_sloping_up   = ema20_15 > prev_ema20 if ema20_15 and prev_ema20 else None
    ema20_sloping_down = ema20_15 < prev_ema20 if ema20_15 and prev_ema20 else None
    macd_accel  = macd > prev_macd
    macd_decel  = macd < prev_macd
    stoch_up    = stoch_rsi > prev_stoch
    stoch_down  = stoch_rsi < prev_stoch
    trending    = adx > 25

    # ── Bullish signals (each +1, max 8) ──────────────────────────────────────
    bull = [
        trend_15m is True,                  # 1. EMA20 above EMA50 on 15m
        trend_1h is True,                   # 2. EMA20 above EMA50 on 1h
        50 < rsi < 72,                      # 3. RSI positive zone, not overbought
        macd > 0 and macd_accel,            # 4. MACD positive AND accelerating
        vol > 1.2,                          # 5. Above-average volume
        ema20_sloping_up is True,           # 6. EMA20 sloping upward
        stoch_rsi > 20 and stoch_up,        # 7. StochRSI rising from low zone
        trending,                           # 8. ADX > 25 confirms trend strength
    ]

    # ── Bearish signals (each +1, max 8) ──────────────────────────────────────
    bear = [
        trend_15m is False,                 # 1. EMA20 below EMA50 on 15m
        trend_1h is False,                  # 2. EMA20 below EMA50 on 1h
        28 < rsi < 50,                      # 3. RSI negative zone, not oversold
        macd < 0 and macd_decel,            # 4. MACD negative AND worsening
        vol > 1.2,                          # 5. Above-average volume
        ema20_sloping_down is True,         # 6. EMA20 sloping downward
        stoch_rsi < 80 and stoch_down,      # 7. StochRSI falling from high zone
        trending,                           # 8. ADX > 25 confirms trend strength
    ]

    bull_count = sum(bull)
    bear_count = sum(bear)

    # Require one extra signal in ranging markets
    min_signals = 6 if regime == "ranging" else 5

    # ── ATR-based TP/SL ───────────────────────────────────────────────────────
    sl_pct = round((atr / price) * 100, 2) if price > 0 and atr > 0 else 0.5
    sl_pct = max(sl_pct, 0.1)
    tp_pct = round(sl_pct * 1.5, 2)

    # ── Dynamic position sizing — scales with signal confidence ───────────────
    def _dynamic_size(score: int) -> float:
        confidence = score / 8.0
        base  = MAX_SIZE_USDT * 0.5
        extra = MAX_SIZE_USDT * 0.5
        size  = base + (extra * max(0.0, confidence - 0.5) / 0.5)
        size *= size_regime_factor
        return round(max(15.0, min(MAX_SIZE_USDT, size)), 1)

    meta = {
        "bull_signals":  bull_count,
        "bear_signals":  bear_count,
        "rsi":           rsi,
        "macd_hist":     macd,
        "vol_ratio":     vol,
        "stoch_rsi_k":   stoch_rsi,
        "adx":           adx,
        "regime":        regime,
        "ema_trend_15m": "bull" if trend_15m else ("bear" if trend_15m is False else "unknown"),
        "ema_trend_1h":  "bull" if trend_1h  else ("bear" if trend_1h  is False else "unknown"),
        "sl_pct":        sl_pct,
        "tp_pct":        tp_pct,
    }

    if position is None:
        if bull_count >= min_signals:
            return {"action": "OPEN_LONG",
                    "size_usdt": _dynamic_size(bull_count),
                    "sl_pct": sl_pct, "tp_pct": tp_pct, **meta}
        if bear_count >= min_signals:
            return {"action": "OPEN_SHORT",
                    "size_usdt": _dynamic_size(bear_count),
                    "sl_pct": sl_pct, "tp_pct": tp_pct, **meta}
        return {"action": "WAIT", **meta}

    side = position.get("side", "")
    if side == "BUY" and bear_count >= 3:
        return {"action": "CLOSE",
                "reason": f"{bear_count}/8 bearish signals vs open LONG", **meta}
    if side == "SELL" and bull_count >= 3:
        return {"action": "CLOSE",
                "reason": f"{bull_count}/8 bullish signals vs open SHORT", **meta}
    return {"action": "HOLD", **meta}
