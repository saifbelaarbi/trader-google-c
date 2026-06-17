from agent.config import MAX_SIZE_USDT, MAX_SL_PCT, MIN_TP_SL_RATIO, SYMBOLS


def validate_decision(symbol: str, decision: dict, current_position: dict | None) -> str | None:
    """
    Validate a trade decision against hard risk rules.
    Returns an error string if blocked, None if the decision may proceed.
    Mutates decision["size_usdt"] downward if it exceeds the cap (soft override).
    """
    action = decision.get("action", "WAIT")

    if action == "WAIT":
        return None

    if symbol not in SYMBOLS:
        return f"{symbol} not in allowed symbols: {SYMBOLS}"

    if action in ("OPEN_LONG", "OPEN_SHORT"):
        if current_position is not None:
            return f"Position already open for {symbol} — cannot open another"

        size_usdt = float(decision.get("size_usdt") or 0)
        if size_usdt <= 0:
            return "size_usdt must be positive"
        if size_usdt > MAX_SIZE_USDT:
            decision["size_usdt"] = MAX_SIZE_USDT  # cap silently, don't reject

        tp_pct = float(decision.get("tp_pct") or 0)
        sl_pct = float(decision.get("sl_pct") or 0)
        if tp_pct <= 0 or sl_pct <= 0:
            return "tp_pct and sl_pct must both be positive"
        if sl_pct > MAX_SL_PCT:
            return f"sl_pct {sl_pct}% exceeds maximum {MAX_SL_PCT}%"
        if tp_pct / sl_pct < MIN_TP_SL_RATIO:
            return (f"TP/SL ratio {tp_pct/sl_pct:.2f} below minimum {MIN_TP_SL_RATIO} "
                    f"(tp={tp_pct}% sl={sl_pct}%)")

    if action == "CLOSE":
        if current_position is None:
            return f"No open position for {symbol} to close"

    return None
