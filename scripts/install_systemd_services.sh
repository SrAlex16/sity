#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/alex/projects/sity"

echo "[sity] Installing systemd services..."

sudo cp "$PROJECT_ROOT/deploy/systemd/sity-backend.service" /etc/systemd/system/sity-backend.service
sudo cp "$PROJECT_ROOT/deploy/systemd/sity-frontend.service" /etc/systemd/system/sity-frontend.service
sudo cp "$PROJECT_ROOT/deploy/systemd/sity-test.service" /etc/systemd/system/sity-test.service

echo "[sity] Installing sudoers allowlist..."

sudo cp "$PROJECT_ROOT/deploy/sudoers/sity" /etc/sudoers.d/sity
sudo chmod 0440 /etc/sudoers.d/sity
sudo visudo -c -f /etc/sudoers.d/sity

echo "[sity] Reloading systemd..."

sudo systemctl daemon-reload

echo "[sity] Enabling services..."

sudo systemctl enable sity-backend
sudo systemctl enable sity-frontend
sudo systemctl enable sity-test

echo "[sity] Done."
echo "You can start services with:"
echo "  sudo systemctl start sity-backend"
echo "  sudo systemctl start sity-frontend"
echo "  sudo systemctl start sity-test"
