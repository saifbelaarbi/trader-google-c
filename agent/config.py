SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

# Firestore timeframe strings matching TradingView {{interval}} values
TIMEFRAME_15M = "15"
TIMEFRAME_1H = "60"

# How many historical bars to fetch per symbol per timeframe (8 hours each)
HISTORY_15M = 32   # 32 × 15m = 8 hours
HISTORY_1H = 8     # 8 × 1h = 8 hours

# How often the agent polls for new alerts (seconds)
POLL_INTERVAL_SECONDS = 30

# Risk limits (agent enforces these regardless of Claude's suggestion)
MAX_SIZE_USDT = 40.0
MAX_SL_PCT = 3.0
MIN_TP_SL_RATIO = 1.5
