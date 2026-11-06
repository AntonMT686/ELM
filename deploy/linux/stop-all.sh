#!/usr/bin/env bash
# Stops what start-all.sh started. MySQL, OnlyOffice and GitLab keep running.
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
for s in frontend worker backend; do
  f="$ROOT/logs/$s.pid"; [ -f "$f" ] || continue
  pkill -TERM -P "$(cat "$f")" 2>/dev/null; kill "$(cat "$f")" 2>/dev/null && echo "stopped $s"; rm -f "$f"
done
