#!/usr/bin/env bash
# ADA-ELM background worker in the foreground (Ctrl+C stops it).
cd "$(dirname "$0")/../../backend" && exec .venv/bin/python -m app.worker
