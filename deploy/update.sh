#!/usr/bin/env bash
# deploy/update.sh — Pull latest code and restart the Rift Tap server.
#
# Usage:
#   bash deploy/update.sh
#
# What it does:
#   1. Stops the running rift-tap service
#   2. Pulls the latest code from GitHub
#   3. Restarts the service
#
# The script works whether the server is running via systemd (production)
# or started manually. It detects which case applies automatically.

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[update]${NC} $*"; }
warn() { echo -e "${YELLOW}[update]${NC} $*"; }

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

# ── 1. Stop the server ────────────────────────────────────────────────────────
if systemctl is-active --quiet rift-tap 2>/dev/null; then
    info "Stopping rift-tap service..."
    sudo systemctl stop rift-tap
    USING_SYSTEMD=true
else
    warn "rift-tap service not running via systemd"
    USING_SYSTEMD=false
fi

# ── 2. Pull latest code ───────────────────────────────────────────────────────
info "Pulling latest code..."
git pull --ff-only

# ── 3. Restart ────────────────────────────────────────────────────────────────
if [[ "$USING_SYSTEMD" == "true" ]]; then
    info "Starting rift-tap service..."
    sudo systemctl start rift-tap
    sleep 2
    sudo systemctl status rift-tap --no-pager --lines=8
else
    info "Starting server manually (use Ctrl+C to stop)..."
    source .venv/bin/activate
    exec python -m uvicorn src.server:app --host 0.0.0.0 --port 8000
fi
