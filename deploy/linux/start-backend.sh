#!/usr/bin/env bash
# ADA-ELM backend API in the foreground (Ctrl+C stops it).
cd "$(dirname "$0")/../../backend" && exec .venv/bin/python -m app.serve "$@"
