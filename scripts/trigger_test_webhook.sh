#!/usr/bin/env bash
set -euo pipefail

URL=${1:?"Usage: ./trigger_test_webhook.sh <url> [action]"}
ACTION=${2:-"BUY"}
SECRET=${WEBHOOK_SECRET:?"Set WEBHOOK_SECRET env var"}

PAYLOAD=$(cat <<EOF
{
  "symbol": "BTCUSDT",
  "action": "$ACTION",
  "price": 65000.00,
  "tp_pct": 1.0,
  "sl_pct": 0.5,
  "size_usdt": 20,
  "timeframe": "5",
  "strategy": "test_manual"
}
EOF
)

echo "Sending $ACTION signal to $URL"
curl -s -X POST "$URL/webhook" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: $SECRET" \
  -d "$PAYLOAD" | python3 -m json.tool
