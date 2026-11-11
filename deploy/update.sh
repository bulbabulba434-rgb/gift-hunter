#!/usr/bin/env bash
# Pull the latest code from GitHub and restart the bot. Usage: bash deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
.venv/bin/pip install -q -r requirements.txt
sudo systemctl restart gift-hunter
sleep 3
systemctl --no-pager status gift-hunter | head -n 5
