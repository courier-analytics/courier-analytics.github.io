#!/usr/bin/env bash
set -euo pipefail
base=/opt/courier-analytics
scripts="$base/dashboard-code/tools"
(
exec 9>"$base/refresh.lock"
flock -w 120 9
"$base/import-venv/bin/python" - "$scripts" <<'PY'
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from refresh_dashboard import merge_feed
from enrich_slots import atomic_json
saved=json.loads(Path('/opt/courier-analytics/dashboard-code/data/dashboard.json').read_text())
recovery=json.loads((Path(sys.argv[1])/'recoveries/ds-7745-2026-11-03.json').read_text())
for row in saved['records']:
    if row['date']==recovery['date'] and row['shop_id']==recovery['shop_id']:
        for key,entry in recovery['last_successes'].items():
            if row.get('metrics',{}).get(key,{}).get('value') is None:
                row['metrics'][key]={**entry['metric'],'last_success_at':entry['at'],
                    'stale_reason':row['metrics'][key]['reason']}

path=Path('/opt/courier-analytics/current-site/data/dashboard.json')
current=json.loads(path.read_text());atomic_json(path,merge_feed(saved,current));path.chmod(0o644)
PY
flock -w 120 "$base/publish.lock" "$base/import-venv/bin/python" "$scripts/publish_dashboard.py" --feed "$base/current-site/data/dashboard.json"
)
bash "$scripts/update_private_frontend.sh"
systemctl start courier-web-data.service
journalctl -u courier-onec-roster.service -n 25 --no-pager
