#!/usr/bin/env bash
set -euo pipefail
base=/opt/courier-analytics
scripts="$base/dashboard-code/tools"
exec 8>"$base/medical.lock"
flock -w 5 8
python3 "$scripts/probe_powerbi_vpn.py" --address 10.0.112.18 --collect-medical
flock -w 120 "$base/publish.lock" python3 "$scripts/publish_dashboard.py" --medical --feed "$base/private/medical-books-candidate.json"
