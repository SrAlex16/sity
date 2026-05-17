#!/usr/bin/env bash
set -euo pipefail

SERVICES=(
  "sity-backend"
  "sity-frontend"
  "sity-test"
)

for service in "${SERVICES[@]}"; do
  echo "== $service =="
  systemctl is-enabled "$service" || true
  systemctl is-active "$service" || true
  echo
done

echo "Backend health:"
curl -s http://localhost:8000/health || true
echo

echo "Sity test service:"
curl -s http://localhost:8099 || true
echo
