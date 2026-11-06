#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/courier-analytics/dashboard-code
exec 9>/opt/courier-analytics/refresh.lock
flock -w 180 9
PY=/opt/courier-analytics/import-venv/bin/python
FEED=/opt/courier-analytics/current-site/data/dashboard.json
"$PY" tools/recalculate_completion.py --feed "$FEED"
flock -w 120 /opt/courier-analytics/publish.lock "$PY" tools/publish_dashboard.py --feed "$FEED"
systemctl start courier-web-data.service
