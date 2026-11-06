#!/usr/bin/env bash
# Starts backend, worker and frontend in the background; logs in <repo>/logs, PIDs in <repo>/logs/*.pid.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd); mkdir -p "$ROOT/logs"
start() { nohup "$ROOT/deploy/linux/start-$1.sh" > "$ROOT/logs/$1.log" 2>&1 & echo $! > "$ROOT/logs/$1.pid"; echo "started $1 (pid $(cat "$ROOT/logs/$1.pid"))"; }
start backend; sleep 8; start worker; start frontend
echo "Open http://localhost:$(grep -E '^ELM_WEB_PORT=' "$ROOT/.env" | cut -d= -f2 || echo 8088)"
