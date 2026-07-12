#!/bin/bash
# Restart the LocalWiki Streamlit app (port 8520) to pick up code changes
# WITHOUT dropping the Cloudflare quick-tunnel URL.
#
# Why this is not just `pkill + relaunch`: tunnel.sh ends in a watchdog loop
# (`while lsof -ti:8520 ...; do sleep 3; done; kill $TUNNEL_PID`) that tears the
# tunnel down once the app stops listening. A naive kill fires it and the public
# URL changes. So we: disarm the watchdog, SIGTERM the app, relaunch it exactly
# as tunnel.sh does, then arm an equivalent watchdog aimed at the SAME tunnel
# PID. The cloudflared process itself is never touched.
#
# `Ctrl-C` on tunnel.sh still intentionally tears both down.

set -o pipefail

PORT=8520
LOG=/tmp/wiki-tunnel.log
APP_LOG=/tmp/wiki-app.log
URL_FILE=/tmp/wiki-app-url.txt
APP_PATTERN="streamlit run src/app.py --server.port $PORT"
TUNNEL_PATTERN="cloudflared tunnel --url http://localhost:$PORT"

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null) || REPO="$SCRIPT_DIR/../../../.."
REPO=$(cd "$REPO" && pwd)

say() { echo "[restart-app] $*"; }

port_up()   { lsof -ti:"$PORT" >/dev/null 2>&1; }
wait_port() { # wait_port up|down <seconds>
  local want=$1 secs=$2 i
  for i in $(seq 1 "$secs"); do
    if [ "$want" = up ];   then port_up && return 0; fi
    if [ "$want" = down ]; then port_up || return 0; fi
    sleep 1
  done
  return 1
}

# 1. Locate the tunnel we must preserve.
TUNNEL_PID=$(pgrep -f "$TUNNEL_PATTERN" | head -1)
if [ -z "$TUNNEL_PID" ]; then
  say "No quick tunnel is running — nothing to preserve."
  say "Restarting the app only; run ./tunnel.sh to (re)create a public URL."
fi

# 2. Disarm the watchdog(s) BEFORE touching the app, so restarting the app cannot
#    trigger a tunnel teardown. Two shapes exist:
#      a) a live `tunnel.sh` supervisor still in its while-loop. SIGKILL it — its
#         `trap ... INT TERM` would kill the tunnel on the way out. Its
#         restore_config step ran seconds after start, so skipping it loses nothing.
#      b) a detached `bash -c 'while lsof -ti ...'` watchdog armed by a previous
#         run of this script.
#    Both are matched only when they belong to THIS repo (other projects run their
#    own tunnels on other ports — never disarm those).
SUPERVISORS=""
for pid in $(pgrep -f "tunnel\.sh" || true); do
  [ "$(readlink -f "/proc/$pid/cwd" 2>/dev/null)" = "$REPO" ] && SUPERVISORS="$SUPERVISORS $pid"
done
WATCHDOGS=""
for pid in $(pgrep -f "while lsof -ti" || true); do
  tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q " $PORT " \
    && WATCHDOGS="$WATCHDOGS $pid"
done
if [ -n "$SUPERVISORS" ]; then
  say "Disarming tunnel.sh supervisor(s): $(echo "$SUPERVISORS" | tr '\n' ' ')"
  # shellcheck disable=SC2086
  kill -KILL $SUPERVISORS 2>/dev/null || true
fi
if [ -n "$WATCHDOGS" ]; then
  say "Disarming watchdog(s): $(echo "$WATCHDOGS" | tr '\n' ' ')"
  # shellcheck disable=SC2086
  kill $WATCHDOGS 2>/dev/null || true
fi

# 3. Stop the app (SIGTERM its own process) and wait for the port to free.
if port_up; then
  say "Stopping app on port $PORT (SIGTERM)..."
  pkill -TERM -f "$APP_PATTERN" 2>/dev/null || true
  if ! wait_port down 15; then
    say "Port $PORT still busy after 15s; sending SIGKILL to the app."
    pkill -KILL -f "$APP_PATTERN" 2>/dev/null || true
    wait_port down 10 || { say "ERROR: port $PORT never freed; aborting."; exit 1; }
  fi
else
  say "App was not running."
fi

# 4. Relaunch exactly as tunnel.sh does, but in its own session (setsid) and
#    immune to SIGHUP (nohup), headless, detached, logging to the same file.
say "Relaunching app from $REPO ..."
( cd "$REPO" && setsid nohup uv run streamlit run src/app.py \
    --server.port "$PORT" --server.headless true \
    < /dev/null > "$APP_LOG" 2>&1 & )

if ! wait_port up 30; then
  say "ERROR: app did not start within 30s. Last 20 app-log lines:"
  tail -20 "$APP_LOG"
  exit 1
fi
APP_PID=$(pgrep -f "$APP_PATTERN" | head -1)
say "App is listening on port $PORT (pid ${APP_PID:-?})."

# 5. Arm a watchdog aimed at the SAME tunnel PID, matching tunnel.sh's tail. The
#    PID is passed as an argument, not embedded as a pkill pattern, so the
#    watchdog can't match and kill itself.
if [ -n "$TUNNEL_PID" ] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
  setsid nohup bash -c '
    port=$1; tunnel_pid=$2; url_file=$3
    while lsof -ti:"$port" >/dev/null 2>&1; do sleep 3; done
    kill "$tunnel_pid" 2>/dev/null
    rm -f "$url_file"
  ' _ "$PORT" "$TUNNEL_PID" "$URL_FILE" < /dev/null >> "$LOG" 2>&1 &
  say "Armed watchdog for tunnel pid $TUNNEL_PID."
  URL=$(cat "$URL_FILE" 2>/dev/null)
  say "Tunnel preserved. Public URL: ${URL:-<see $URL_FILE>}"
elif [ -n "$TUNNEL_PID" ]; then
  say "WARNING: tunnel pid $TUNNEL_PID vanished during restart; URL is gone."
  say "Run ./tunnel.sh to create a new public URL."
fi

say "Done. App log: $APP_LOG"
