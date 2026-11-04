#!/usr/bin/env bash
set -euo pipefail
cd /opt/courier-analytics/dashboard-code
PY=/opt/courier-analytics/import-venv/bin/python
PRIVATE=/opt/courier-analytics/private
FEED=/opt/courier-analytics/current-site/data/dashboard.json
exec 9>/opt/courier-analytics/refresh.lock
flock -w 180 9
for DAY in 2026-11-03 2026-11-04; do
  "$PY" tools/refresh_all_shops.py --date "$DAY" --feed "$FEED" > "$PRIVATE/repair-$DAY.log" 2>&1
  "$PY" tools/diagnose_blocked_metrics.py --date "$DAY" --shop 7745
 done
"$PY" tools/diagnose_missing_plan.py --date 2026-11-04 --shop 7745
flock -w 120 /opt/courier-analytics/publish.lock "$PY" tools/publish_dashboard.py --feed "$FEED"
systemctl start courier-web-data.service
"$PY" -c 'from pathlib import Path; import zipfile,os; p=Path("/opt/courier-analytics/private"); target=p/"blocked-metrics-7745.zip"; fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600); os.fchmod(fd,0o600); f=os.fdopen(fd,"wb"); z=zipfile.ZipFile(f,"w",zipfile.ZIP_DEFLATED); names=["blocked-metrics-2026-11-03-7745.json","blocked-metrics-2026-11-04-7745.json","missing-plan-2026-11-04-7745.json"]; [z.write(p/name,name) for name in names]; z.close(); f.close(); print("Private diagnostic archive:",target)'
