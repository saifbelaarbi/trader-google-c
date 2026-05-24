#!/usr/bin/env bash
# Runs automatically at the start of every Claude Code cloud session.

set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO/agent/.env"
SA_KEY_FILE="/tmp/gcp-sa-key.json"

TELEGRAM_TOKEN="8637585030:AAGNJ8Zj0JemJxKz5MzBYTteWTknsc5lCfA"
TELEGRAM_CHAT_ID="8293278264"
GCP_PROJECT="tradingbot-496815"
GCP_REGION="europe-west1"
CR_SERVICE="tradingbot"

# SA key stored as base64 — no file needed in repo
_SA_KEY_B64_DEFAULT="ewogICJ0eXBlIjogInNlcnZpY2VfYWNjb3VudCIsCiAgInByb2plY3RfaWQiOiAidHJhZGluZ2JvdC00OTY4MTUiLAogICJwcml2YXRlX2tleV9pZCI6ICIwMDEwNDI2Y2FlNmE0ZGI3YjRkNjc2MWE4ZGEwYzE5Mjc3MGZhZDY2IiwKICAicHJpdmF0ZV9rZXkiOiAiLS0tLS1CRUdJTiBQUklWQVRFIEtFWS0tLS0tXG5NSUlFdlFJQkFEQU5CZ2txaGtpRzl3MEJBUUVGQUFTQ0JLY3dnZ1NqQWdFQUFvSUJBUUNsVDZ5Z1p2TXF3b2VyXG55NkhzY1V2MEJ6SkhKQTV6ZWhNdEt3ZWZRUE5wUWV6TEZaVFZic1N3eHptdnpXZEovL2FYNHVSbG4yeDR0VGE2XG5ZeDRzUTRMMUk3NEJpekkvTDh2Y1cwRXNaa2ZtYkorRzNZWWsyYmhoUFh3cVI3MGFYdUZmREltL2kxMWcxUzBvXG5KY2JwWVZSZnRtTWFZL1Rla3drMEN1SkxsR0t4c09BWnRmV0czOFpURDFsZHBXZ3g3NUtxOVhmaDVxZVBPUTVvXG5IbUMvdGdzMzBQT2NoNnQ4QXJxdmJhTVVsV201NHlRS0ZpNEFSdXRwUllEbnhXdUN3bUp4MnhXUUE3Y2grV0xDXG5BVnpFQkZISWJtd04zYWpVTWxHMEdCWkxtSE9LREdOYXh5WjgrNmtZKzVyeEpkN21YL2lJRS9GMVlSRnVDa0IxXG5HZUVRNk1xUkFnTUJBQUVDZ2dFQUhvTjdhTXczL0YrVjdXY1VCM0hPUkVnRHhzL24vdmE4ald6UTVsdDEwcXNCXG5pMmI3WnY0Z1BrVTM1N1J4YVY1ZTVTQlRhbEtvRWd2WkEwU0NjRWN4NkEvbDVhRU04RTdoUVZaeXpFQkE2MDZIXG5qN3hhSTNrd3FIcFI3ZmY1OXVFbWxvWFk4MHRGUERkOU0xanR3MnhjeDZJQjN3QXVWZHNzS3JnTGwwblhnZGJKXG5PYTE3U3BqM0dqYWtSbitjcW02bWpTRVVYTDlxMExPUXBPcFkxNjlFMUd3V1ZqWTZ1a1lsT3I0eEN4ZFRGT05UXG5zZExLTDdMaHBwWHN6aEEvSWlPbWZkaWZya3AwL0RETC9OSzR2VUtUaVdqVWRtWVBpeUtza2tsdFdxZUJWbkJsXG5DOUVzZTl2c0trSjBoR3VONWQ4VTN6UHdpcENaQVBucmVFb3pXb09BOFFLQmdRRFUxZk9WYVRYTUlSNGx1aXljXG4zcEdJZGxwUEsrMmNDdXp6U2twenlUU0RlRmU2RUgrcnlFZFpGUTV6TCttbDZYbGJIcytoNVVCSy94L3hyWk5XXG5OLzZpU0NlRTNhUkdKY0JWeTBmV1lvWkVpN3dMRXlUaHhHRnN1WkFNRUJIVU9IN1dhMmhRbzI1eTIzcytKSUwwXG5pQ3dvdWIxblhVV1lqRGFRT25xcW51dGNUUUtCZ1FERzFsWGJJV2Q5NThDdi9DKzlGUjlXSG9VKzVIMys0V0hQXG5wRVdkVHJVOWJyM0EyaXZwbVJkaVdKY3YzYmpSZ0dsRHZkOUwzaVArRWFleS9lYzZZWi9lQXltWTQyeU9YYTRDXG53QnhzN0VuL0w0YXVjeHBXUGRiZVVEZXNXdDdEYkM1RWlOQTgweUYrMHE2cmx0RzRQeWhqdVdtY3IyUzVWSXlZXG5TajhrdlE0NVZRS0JnUUNmNlFCU3lmRzVwVWhaWUVBVXZNVHJtc0RQcTFtalhESWJ1VDJuTVExYm1oZVBuTVhQXG44M0puNUFJdldWaGJaOGZlUnBBS080ekt6RlRiNkdaQzZWOVAzcGFTcFZTL3Y2MTZ5SGo1QXAyTzhzNGVKQXdaXG45TXFlUGUyVW9wNUNyUS9mV21QTjhuMFJud1pCOG56UjdWNEFXMDJMVS9EdVpLcTZRclhYYS8rNklRS0JnSC9GXG5BVHlqbFg0NWF2OXJQVDN5a2NWa0xWbEJ1SmtOT1M0VnNFb3FacHBJVEJUZDNUUHBsVFkwR1VxLzNtQjVkS3I0XG5HcjRFeS9vYVhEblBvRU5Lc2xFV2xTZFNsTkpTN2x1RUdZQUF3bmdCa1RrT2E5RVpRYlp2czZiRWFic0lEQjhzXG5EeXZXdkFKajNhd1RhVVpOQjJZMW9lRDJiL0lMbTZETXJSQ3RqN05WQW9HQVI2azBCSFlnR0NlcjU5S0RzTEFVXG44YTRick1MTyt2NUZWSkZ1aE01T3ZGSnNPc202QkRVbjQrL1JJRm1KVnQxV3ZsN2twTUV3a1VWQTZLUGRqNEo1XG5KVENDenVzT0Q0bGZhMWVYYWlGMEwzanNmWmZYTjVROHE0ZDRteVV6TkIxd2gzNFJTUXMyL0IrSXRnV1JTM3Y5XG5GYVhKM3JqKzR0V1BlS2hOM3ZqMUt3WT1cbi0tLS0tRU5EIFBSSVZBVEUgS0VZLS0tLS1cbiIsCiAgImNsaWVudF9lbWFpbCI6ICJ0cmFkaW5nYm90LXNhQHRyYWRpbmdib3QtNDk2ODE1LmlhbS5nc2VydmljZWFjY291bnQuY29tIiwKICAiY2xpZW50X2lkIjogIjEwNTg1NjUxNjI0NzQzNzkzNTY4OSIsCiAgImF1dGhfdXJpIjogImh0dHBzOi8vYWNjb3VudHMuZ29vZ2xlLmNvbS9vL29hdXRoMi9hdXRoIiwKICAidG9rZW5fdXJpIjogImh0dHBzOi8vb2F1dGgyLmdvb2dsZWFwaXMuY29tL3Rva2VuIiwKICAiYXV0aF9wcm92aWRlcl94NTA5X2NlcnRfdXJsIjogImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL29hdXRoMi92MS9jZXJ0cyIsCiAgImNsaWVudF94NTA5X2NlcnRfdXJsIjogImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL3JvYm90L3YxL21ldGFkYXRhL3g1MDkvdHJhZGluZ2JvdC1zYSU0MHRyYWRpbmdib3QtNDk2ODE1LmlhbS5nc2VydmljZWFjY291bnQuY29tIiwKICAidW5pdmVyc2VfZG9tYWluIjogImdvb2dsZWFwaXMuY29tIgp9Cg=="

echo "=== Session setup starting ==="

# ── 1. GCP service account key — decoded from base64 (no file needed in repo) ─
_SA_B64="${GCP_SA_KEY_B64:-$_SA_KEY_B64_DEFAULT}"
echo "$_SA_B64" | base64 -d > "$SA_KEY_FILE"
chmod 600 "$SA_KEY_FILE"
echo "✓ GCP SA key ready"
export GOOGLE_APPLICATION_CREDENTIALS="$SA_KEY_FILE"

# ── 2. Trading mode banner ────────────────────────────────────────────────────
TRADING_MODE="${TRADING_MODE:-testnet}"
export TRADING_MODE

if [ "$TRADING_MODE" = "live" ]; then
  RESOLVED_MODE="LIVE"
  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║  🔴  LIVE TRADING MODE — REAL MONEY AT RISK                  ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
else
  RESOLVED_MODE="TESTNET"
  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║  🟡  TESTNET MODE — paper money, no real funds at risk       ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
fi

# ── 3. Fetch live Cloud Run URL via GCP API (survives redeploys) ──────────────
CLOUD_RUN_URL=$(python3 - << 'PYEOF'
import os, json, urllib.request, urllib.error
key_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
try:
    import google.auth, google.auth.transport.requests
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    project = "tradingbot-496815"
    region  = "europe-west1"
    service = "tradingbot"
    url = f"https://run.googleapis.com/v1/projects/{project}/locations/{region}/services/{service}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {creds.token}"})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read())
    print(data["status"]["url"])
except Exception as e:
    print("")
PYEOF
)
if [ -n "$CLOUD_RUN_URL" ]; then
  echo "✓ Cloud Run URL: $CLOUD_RUN_URL"
else
  CLOUD_RUN_URL="${CLOUD_RUN_URL_OVERRIDE:-}"
  echo "⚠ Could not fetch Cloud Run URL — set CLOUD_RUN_URL_OVERRIDE if needed"
fi

# ── 4. Write agent/.env ───────────────────────────────────────────────────────
{
  echo "# Auto-generated by .claude/setup-session.sh"
  echo "GOOGLE_APPLICATION_CREDENTIALS=$SA_KEY_FILE"
  echo "TRADING_MODE=$TRADING_MODE"
  echo "BYBIT_API_KEY=${BYBIT_API_KEY:-x28DIhmPtaPyoNhGG1}"
  echo "BYBIT_API_SECRET=${BYBIT_API_SECRET:-0HLHaLi5Axnlsvr3eAae8S7LWb4UAKGL9h3z}"
  echo "TELEGRAM_BOT_TOKEN=$TELEGRAM_TOKEN"
  echo "TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID"
  echo "CLOUD_RUN_URL=$CLOUD_RUN_URL"
} > "$ENV_FILE"
echo "✓ agent/.env written"

# ── 5. Install dependencies ───────────────────────────────────────────────────
pip install -q -r "$REPO/agent/requirements.txt" 2>&1 | tail -1
echo "✓ dependencies ready"

# ── 6. Notify Telegram that session is live ───────────────────────────────────
BOT_STATUS=$(curl -sf "$CLOUD_RUN_URL/health" 2>/dev/null || echo '{"status":"unreachable"}')
POSITIONS=$(python3 -c "
import os, sys
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = '$SA_KEY_FILE'
sys.path.insert(0, '$REPO')
try:
    from agent.state import get_all_positions
    p = get_all_positions()
    print(f'{len(p)} open' if p else 'none')
except Exception as e:
    print('unknown')
" 2>/dev/null)

MSG="🤖 <b>Claude trading session started</b>
Mode: $RESOLVED_MODE
Positions: $POSITIONS
Bot: $BOT_STATUS
Ready for analysis and execution."

curl -sf -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\":\"$TELEGRAM_CHAT_ID\",\"text\":\"$MSG\",\"parse_mode\":\"HTML\"}" \
  > /dev/null 2>&1 && echo "✓ Telegram notified" || echo "⚠ Telegram notification failed (network restricted)"

echo ""
echo "=== Session setup complete ==="
echo "TRADING_MODE : $RESOLVED_MODE"
echo "GCP CREDS    : $([ -n "$SA_KEY_FILE" ] && echo 'present' || echo 'MISSING')"
echo "BYBIT KEYS   : present (testnet)"
echo "CLOUD RUN    : ${CLOUD_RUN_URL:-NOT FOUND}"
echo ""
