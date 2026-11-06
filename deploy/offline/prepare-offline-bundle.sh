#!/usr/bin/env bash
# ADA-ELM offline package for a LINUX x86_64 server, built on a connected Linux PC (same distro family recommended).
#   deploy/offline/prepare-offline-bundle.sh [version] [python-version]     e.g. 0.2.0 3.12
# Set WITH_ONLYOFFICE=1 and/or WITH_DRAWIO=1 to also save those Docker images.
set -euo pipefail
VER=${1:-0.2.0}; PYV=${2:-3.12}
ROOT=$(cd "$(dirname "$0")/../.." && pwd); OUT="$ROOT/dist/ada-elm-offline-$VER"
mkdir -p "$OUT/offline/wheels" "$OUT/offline/npm-cache" "$OUT/offline/images"
rsync -a --exclude node_modules --exclude .venv --exclude __pycache__ --exclude data --exclude dist --exclude logs --exclude .git --exclude _to_delete \
      --exclude .env --exclude '*.db' --exclude 'pms_bundle*' "$ROOT/" "$OUT/"
cp "$ROOT/Docs/OFFLINE_DEPLOYMENT.md" "$OUT/README-OFFLINE.md"
python3 -m pip download -r "$ROOT/backend/requirements.txt" pip setuptools wheel -d "$OUT/offline/wheels" --only-binary=:all: --platform manylinux2014_x86_64 --python-version "$PYV" --implementation cp
(cd "$OUT/frontend" && npm ci --no-audit --no-fund --cache "$OUT/offline/npm-cache" && VITE_DEMO_HINT=0 npm run build && rm -r node_modules)
if [ "${WITH_ONLYOFFICE:-0}" = 1 ]; then docker pull onlyoffice/documentserver:8.2.2 && docker save -o "$OUT/offline/images/onlyoffice-documentserver-8.2.2.tar" onlyoffice/documentserver:8.2.2; fi
if [ "${WITH_DRAWIO:-0}" = 1 ]; then docker pull jgraph/drawio:24.7.17 && docker save -o "$OUT/offline/images/drawio-24.7.17.tar" jgraph/drawio:24.7.17; fi
(cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | xargs -0 sha256sum > SHA256SUMS)
tar -C "$ROOT/dist" -czf "$ROOT/dist/ada-elm-offline-$VER.tar.gz" "ada-elm-offline-$VER"
echo "Done: dist/ada-elm-offline-$VER.tar.gz"
