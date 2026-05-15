import logging
from datetime import datetime

from app import broker, state

logger = logging.getLogger(__name__)


def run_reconciliation() -> dict:
    firestore_positions = state.get_all_positions()
    binance_positions = broker.get_open_positions()

    binance_symbols = {p["symbol"] for p in binance_positions}
    cleared = []

    for position in firestore_positions:
        symbol = position["symbol"]
        if symbol not in binance_symbols:
            state.clear_position(symbol)
            state.log_trade({"event": "reconciled_close", "symbol": symbol})
            cleared.append(symbol)
            logger.info("Reconciliation: cleared ghost position for %s", symbol)

    result = {
        "checked": len(firestore_positions),
        "cleared": cleared,
        "timestamp": datetime.utcnow().isoformat(),
    }

    logger.info(
        "Reconciliation complete: checked=%d cleared=%d", result["checked"], len(cleared)
    )

    return result
