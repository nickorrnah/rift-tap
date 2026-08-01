#!/usr/bin/env bash
# deploy/start.sh — Start the Rift Tap server manually.
#
# Use this for development or testing.
# For production (auto-start on boot), use the systemd service instead:
#   sudo systemctl start rift-tap
#
# Usage (from the project root):
#   bash deploy/start.sh
#   bash deploy/start.sh --reload    # auto-restart on file changes (dev mode)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$APP_DIR/.venv"

if [[ ! -f "$VENV/bin/activate" ]]; then
    echo "ERROR: Virtual environment not found at $VENV"
    echo "Run deploy/setup.sh first, or manually create the venv."
    exit 1
fi

source "$VENV/bin/activate"
cd "$APP_DIR"

RELOAD="${1:-}"
if [[ "$RELOAD" == "--reload" ]]; then
    echo "[rift-tap] Starting in development mode (--reload)..."
    exec python -m uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
else
    echo "[rift-tap] Starting server..."
    exec python -m uvicorn src.server:app --host 0.0.0.0 --port 8000
fi
