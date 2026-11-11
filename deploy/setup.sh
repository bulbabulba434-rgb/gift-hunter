#!/usr/bin/env bash
# First-time setup on an Ubuntu server: python venv + systemd service that restarts on failure/reboot.
# Usage (from the project folder): bash deploy/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

sudo apt-get update -y -qq
sudo apt-get install -y -qq python3-venv python3-pip git

# 1 GB machines: a little swap keeps pip and Telethon comfortable
if [ ! -f /swapfile ]; then
  sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

[ -f .env ] || { echo "Нет файла .env — скопируй его на сервер"; exit 1; }
chmod 600 .env

sudo cp deploy/gift-hunter.service /etc/systemd/system/gift-hunter.service
sudo sed -i "s|__DIR__|$PWD|g; s|__USER__|$USER|g" /etc/systemd/system/gift-hunter.service
sudo systemctl daemon-reload
sudo systemctl enable --now gift-hunter
sleep 3
systemctl --no-pager status gift-hunter | head -n 5
