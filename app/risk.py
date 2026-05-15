REQUIRED_FIELDS = ["symbol", "action", "price", "tp_pct", "sl_pct", "size_usdt"]
VALID_ACTIONS = {"BUY", "SELL", "CLOSE"}
MAX_SIZE_USDT = 500.0
MAX_SL_PCT = 3.0
MIN_TP_SL_RATIO = 1.2
MIN_PRICE = 0.0
ALLOWED_SYMBOLS = None  # TODO: set to list like ["BTCUSDT", "ETHUSDT"] to whitelist


def validate_signal(payload: dict) -> None:
    action = payload.get("action")

    if action != "CLOSE":
        for field in REQUIRED_FIELDS:
            if field not in payload:
                raise ValueError(f"Missing required field: {field}")
    else:
        for field in ["symbol", "action"]:
            if field not in payload:
                raise ValueError(f"Missing required field: {field}")

    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action '{action}'. Must be one of {VALID_ACTIONS}")

    if action == "CLOSE":
        return

    price = payload["price"]
    if not isinstance(price, (int, float)) or price <= MIN_PRICE:
        raise ValueError(f"price must be > 0, got {price}")

    size_usdt = payload["size_usdt"]
    if not isinstance(size_usdt, (int, float)) or size_usdt <= 0:
        raise ValueError(f"size_usdt must be > 0, got {size_usdt}")
    if size_usdt > MAX_SIZE_USDT:
        raise ValueError(f"size_usdt {size_usdt} exceeds MAX_SIZE_USDT {MAX_SIZE_USDT}")

    sl_pct = payload["sl_pct"]
    if not isinstance(sl_pct, (int, float)) or sl_pct <= 0:
        raise ValueError(f"sl_pct must be > 0, got {sl_pct}")
    if sl_pct > MAX_SL_PCT:
        raise ValueError(f"sl_pct {sl_pct} exceeds MAX_SL_PCT {MAX_SL_PCT}")

    tp_pct = payload["tp_pct"]
    if not isinstance(tp_pct, (int, float)) or tp_pct <= 0:
        raise ValueError(f"tp_pct must be > 0, got {tp_pct}")

    if tp_pct / sl_pct < MIN_TP_SL_RATIO:
        raise ValueError(
            f"tp/sl ratio {tp_pct / sl_pct:.2f} is below MIN_TP_SL_RATIO {MIN_TP_SL_RATIO}"
        )

    if ALLOWED_SYMBOLS is not None and payload["symbol"] not in ALLOWED_SYMBOLS:
        raise ValueError(f"Symbol '{payload['symbol']}' not in ALLOWED_SYMBOLS {ALLOWED_SYMBOLS}")
