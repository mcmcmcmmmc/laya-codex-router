#!/bin/bash
# Laya Router watchdog — restarts jev_server.py if it stops answering.
# Cron-friendly: silent on success, always exit 0.
if curl -s -m 5 http://127.0.0.1:4319/health >/dev/null 2>&1; then
  exit 0
fi
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$HOME/.codex/codex-router/jev-watchdog.log"
PYTHON="${JEV_PYTHON:-$(command -v /usr/local/bin/python3 || command -v python3)}"
BACKEND="$(cat "$HOME/.codex/codex-router/decision-backend" 2>/dev/null || printf 'laya')"
if [ -z "${JEV_PYTHON:-}" ] && [ "$BACKEND" != jev ]; then
  PYTHON="$REPO/../laya/.venv/bin/python"
fi
# Laya warms its model before opening the port; avoid a second cold-start process.
if pgrep -f "$REPO/server/jev_server.py" >/dev/null; then
  exit 0
fi
echo "[$(date '+%Y-%m-%dT%H:%M:%S')] server down → restart" >> "$LOG"
cd "$REPO" || exit 1
nohup "$PYTHON" "$REPO/server/jev_server.py" </dev/null >> "$LOG" 2>&1 &
for attempt in {1..90}; do
  curl -sf -m 2 http://127.0.0.1:4319/health >/dev/null 2>&1 && break
  sleep 1
done
if curl -s -m 5 http://127.0.0.1:4319/health >/dev/null 2>&1; then
  echo "[$(date '+%Y-%m-%dT%H:%M:%S')] restarted OK" >> "$LOG"
else
  echo "[$(date '+%Y-%m-%dT%H:%M:%S')] RESTART FAILED" >> "$LOG"
fi
exit 0
