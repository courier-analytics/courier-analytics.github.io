#!/usr/bin/env bash
set -euo pipefail
scripts=/opt/courier-analytics/dashboard-code/tools
base=/opt/courier-analytics
flock -w 120 "$base/onec-roster.lock" "$base/onec-venv/bin/python" "$scripts/probe_powerbi_vpn.py" --address 10.210.254.19 --onec-login --onec-inspect-roster
(
  exec 9>"$base/refresh.lock"
  flock -w 120 9
  "$base/import-venv/bin/python" "$scripts/refresh_all_shops.py" --feed "$base/current-site/data/dashboard.json"
  flock -w 120 "$base/publish.lock" "$base/import-venv/bin/python" "$scripts/publish_dashboard.py" --feed "$base/current-site/data/dashboard.json"
)
bash "$scripts/enable_private_dashboard.sh"
systemctl start courier-web-data.service
printf 'Protected personal detail snapshots:\n'
find /opt/courier-dashboard/details -maxdepth 1 -type f -name '*.json' -printf '%f\n'
echo 'Personal details are available only after login on the protected site.'
