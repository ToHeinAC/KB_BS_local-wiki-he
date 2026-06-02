#!/bin/bash
# Expose LocalWiki (port 8520) via a Cloudflare Quick Tunnel (no account needed).
# Pattern from KB_BS_local-hybrid-researcher/login/start-quick-tunnels.sh,
# adapted to one port + kept alive until port 8520 stops listening.

PORT=8520
LOG=/tmp/wiki-tunnel.log
URL_FILE=/tmp/wiki-app-url.txt
CONFIG=~/.cloudflared/config.yml
CRED_FILE=~/.cloudflared/5bc36850-dc39-48be-81ab-fd15f8071bd0.json

echo "Starting Cloudflare Quick Tunnel for LocalWiki (port $PORT)"
echo "==========================================================="

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared not found. Install: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
  exit 1
fi

# Start the app if nothing is listening on PORT yet
if ! lsof -ti:"$PORT" >/dev/null 2>&1; then
  echo "App not running — starting LocalWiki on port $PORT..."
  uv run streamlit run src/app.py --server.port "$PORT" --server.headless true \
    > /tmp/wiki-app.log 2>&1 &
  echo "  App logs: /tmp/wiki-app.log"
  for i in $(seq 1 30); do
    lsof -ti:"$PORT" >/dev/null 2>&1 && break
    sleep 1
  done
else
  echo "App already running on port $PORT."
fi

# Targeted cleanup of any stale tunnel for THIS port (preserves brain-nw1)
echo "Cleaning up existing tunnel for port $PORT..."
pkill -f "cloudflared tunnel --url http://localhost:$PORT" 2>/dev/null || true
sleep 2

# Move named-tunnel config + creds aside to force TRUE quick-tunnel mode
CONFIG_BACKUP=""
CRED_BACKUP=""
if [ -f "$CONFIG" ]; then
  CONFIG_BACKUP="${CONFIG}.quickbackup"
  mv "$CONFIG" "$CONFIG_BACKUP"
  echo "Temporarily moved config.yml"
fi
if [ -f "$CRED_FILE" ]; then
  CRED_BACKUP="${CRED_FILE}.quickbackup"
  mv "$CRED_FILE" "$CRED_BACKUP"
  echo "Temporarily moved tunnel credentials"
fi

# Always restore config files (idempotent)
restore_config() {
  [ -n "$CONFIG_BACKUP" ] && [ -f "$CONFIG_BACKUP" ] && mv "$CONFIG_BACKUP" "$CONFIG"
  [ -n "$CRED_BACKUP" ]   && [ -f "$CRED_BACKUP" ]   && mv "$CRED_BACKUP" "$CRED_FILE"
}

# Start the quick tunnel (both streams to log)
echo "Starting tunnel..."
nohup cloudflared tunnel --url "http://localhost:$PORT" > "$LOG" 2>&1 &
TUNNEL_PID=$!

# Give it time to register, then restore config
sleep 8
restore_config
echo "Restored config.yml / credentials"

# Extract URL (retry a few extra seconds in case it is slow)
URL=""
for i in $(seq 1 10); do
  URL=$(grep -oP 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1)
  [ -n "$URL" ] && break
  sleep 1
done

echo ""
echo "============================================================"
if [ -n "$URL" ]; then
  echo "$URL" > "$URL_FILE"
  echo "TUNNEL READY"
  echo ""
  echo "  Public URL: $URL"
  echo ""
  echo "  (saved to $URL_FILE)"
else
  echo "URL not found. Last 20 log lines:"
  tail -20 "$LOG"
fi
echo "============================================================"
echo "  Tunnel PID: $TUNNEL_PID | Log: $LOG"
echo "  Tunnel stops automatically when port $PORT closes (or Ctrl-C)."
echo ""

# On Ctrl-C: kill tunnel, restore config (idempotent), exit
trap 'kill $TUNNEL_PID 2>/dev/null; restore_config; echo "Tunnel stopped."; exit 0' INT TERM

# Keep alive until port 8520 stops listening
while lsof -ti:"$PORT" >/dev/null 2>&1; do
  sleep 3
done

echo "Port $PORT no longer listening — stopping tunnel."
kill "$TUNNEL_PID" 2>/dev/null
restore_config
