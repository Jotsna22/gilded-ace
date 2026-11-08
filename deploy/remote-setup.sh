#!/usr/bin/env bash
# Runs on the Vultr Ubuntu box after the app tree is synced to /opt/gilded-ace.
set -euo pipefail

APP_DIR=/opt/gilded-ace
cd "$APP_DIR"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  python3 python3-venv python3-pip python3-dev build-essential ufw curl

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

install -m 644 deploy/gilded-ace.service /etc/systemd/system/gilded-ace.service
systemctl daemon-reload
systemctl enable --now gilded-ace.service

ufw allow OpenSSH
ufw allow 8501/tcp
ufw --force enable

sleep 3
systemctl --no-pager --full status gilded-ace.service || true
curl -fsS "http://127.0.0.1:8501/_stcore/health" && echo " health ok"
