#!/usr/bin/env bash
# Run on a CONNECTED preparation machine with the same CPU arch as the target (x86_64).
# Produces dist/ada-elm-offline-<ver>.tar.gz containing images, source, compose, checksums.
set -euo pipefail
VER=${1:-0.1.0}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT="$ROOT/dist/ada-elm-offline-$VER"
rm -rf "$OUT" && mkdir -p "$OUT/images"
cd "$ROOT"
echo ">> Downloading Python wheels for offline rebuilds"
docker run --rm -v "$ROOT/backend:/w" -w /w python:3.12-slim pip download -r requirements.txt -d /w/wheels
echo ">> Building images"
docker compose build
docker pull postgres:16.6-alpine
for img in ada-elm/backend:0.1.0 ada-elm/web:0.1.0 postgres:16.6-alpine; do
  f="$OUT/images/$(echo "$img" | tr '/:' '__').tar"; docker save "$img" -o "$f"; echo "   saved $img"
done
if [ "${WITH_ONLYOFFICE:-0}" = "1" ]; then docker pull onlyoffice/documentserver:8.2.2 && docker save onlyoffice/documentserver:8.2.2 -o "$OUT/images/onlyoffice.tar"; fi
echo ">> Copying deployment files and source (incl. package-lock & wheels)"
rsync -a --exclude node_modules --exclude dist --exclude '__pycache__' --exclude '*.db' --exclude data "$ROOT/" "$OUT/source/"
cp docker-compose.yml .env.example deploy/scripts/install_offline.sh "$OUT/"
(cd "$OUT" && find . -type f ! -name SHA256SUMS -exec sha256sum {} \; > SHA256SUMS)
tar -C "$ROOT/dist" -czf "$ROOT/dist/ada-elm-offline-$VER.tar.gz" "ada-elm-offline-$VER"
echo ">> Done: dist/ada-elm-offline-$VER.tar.gz"
