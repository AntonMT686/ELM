#!/usr/bin/env bash
# ADA-ELM one-time setup on Linux (no Docker for the application). Run from anywhere:
#   deploy/linux/setup.sh [--offline] [--rebuild-frontend] [--skip-database]
# Safe to run again: .env, data and database rows are kept.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OFFLINE=0; REBUILD=0; SKIPDB=0
[ -d "$ROOT/offline/wheels" ] && OFFLINE=1
for a in "$@"; do case $a in --offline) OFFLINE=1;; --rebuild-frontend) REBUILD=1;; --skip-database) SKIPDB=1;; esac; done
PY=${PYTHON:-python3}
"$PY" -c 'import sys; assert sys.version_info >= (3, 11)' || { echo "Python 3.11+ is required"; exit 1; }
node -e 'process.exit(Number(process.versions.node.split(".")[0]) < 20 ? 1 : 0)' || { echo "Node.js 20+ is required"; exit 1; }
if [ ! -f "$ROOT/.env" ]; then
  sed "s|^ELM_SECRET_KEY=.*|ELM_SECRET_KEY=$("$PY" -c 'import secrets; print(secrets.token_urlsafe(48))')|" "$ROOT/.env.example" > "$ROOT/.env"
  echo "!! $ROOT/.env created. Edit ELM_DATABASE_URL, OnlyOffice and GitLab values, then run this script again."; exit 0
fi
cd "$ROOT/backend"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
if [ $OFFLINE = 1 ]; then .venv/bin/pip install --no-index --find-links "$ROOT/offline/wheels" -r requirements.txt
else .venv/bin/pip install --disable-pip-version-check -r requirements.txt; fi
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then
  if [ $OFFLINE = 1 ]; then npm ci --offline --no-audit --no-fund --cache "$ROOT/offline/npm-cache"; else npm ci --no-audit --no-fund; fi
fi
{ [ $REBUILD = 1 ] || [ ! -f dist/index.html ]; } && npm run build
if [ $SKIPDB = 0 ]; then cd "$ROOT/backend" && .venv/bin/python -m app.dbsetup; fi
echo "Setup complete. Start with deploy/linux/start-all.sh"
