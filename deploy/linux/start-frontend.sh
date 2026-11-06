#!/usr/bin/env bash
# ADA-ELM frontend web server in the foreground: serves frontend/dist and forwards /api to the backend.
# Development with hot reload instead: cd frontend && npm run dev
cd "$(dirname "$0")/../../frontend" && exec npm run serve
