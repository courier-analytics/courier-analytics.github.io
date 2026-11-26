#!/usr/bin/env bash
set -euo pipefail
base=/opt/courier-analytics
exec 8>"$base/refresh.lock"
if ! flock -n 8; then
    echo 'Dashboard refresh deferred: another refresh owns the lock; next timer will retry.'
    exit 75
fi
exec "$base/import-venv/bin/python" "$base/dashboard-code/tools/refresh_recent_days.py" --feed "$base/current-site/data/dashboard.json"
