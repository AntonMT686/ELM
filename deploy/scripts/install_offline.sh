#!/usr/bin/env bash
# Run on the AIR-GAPPED target. No internet access needed.
set -euo pipefail
cd "$(dirname "$0")"
echo ">> Verifying checksums"; sha256sum -c SHA256SUMS --quiet
for f in images/*.tar; do echo ">> Loading $f"; docker load -i "$f"; done
[ -f .env ] || { cp .env.example .env; echo "!! Edit .env (passwords, OnlyOffice URLs/JWT) then re-run"; exit 1; }
docker compose up -d --no-build
echo ">> ADA-ELM is starting on port ${ELM_HTTP_PORT:-8088}. Check: docker compose ps"
