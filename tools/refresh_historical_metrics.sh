#!/usr/bin/env bash
set -euo pipefail
cd /opt/courier-analytics/dashboard-code
DAY=${1:?Pass report date YYYY-MM-DD}
PY=/opt/courier-analytics/import-venv/bin/python
FEED=/opt/courier-analytics/current-site/data/dashboard.json
"$PY" -c 'import sys; from datetime import date; from pathlib import Path; sys.path.insert(0,"tools"); from onec_roster_cache import archive_latest,load_for_day; day=date.fromisoformat(sys.argv[1]).isoformat(); folder=Path("/opt/courier-analytics/private/onec-rosters"); archive_latest(folder); data=load_for_day(folder,day); print("Verified dated 1C roster:",day,data["count"],data["observed_at"])' "$DAY"
exec 9>/opt/courier-analytics/refresh.lock
flock -w 180 9
"$PY" tools/refresh_all_shops.py --date "$DAY" --feed "$FEED"
flock -w 120 /opt/courier-analytics/publish.lock "$PY" tools/publish_dashboard.py --feed "$FEED"
systemctl start courier-web-data.service
