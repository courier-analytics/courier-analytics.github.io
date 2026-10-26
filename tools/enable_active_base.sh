#!/usr/bin/env bash
set -euo pipefail
umask 077
tools_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python=/opt/courier-analytics/import-venv/bin/python
feed=/opt/courier-analytics/current-site/data/dashboard.json
private=/opt/courier-analytics/private
exec 9>/opt/courier-analytics/refresh.lock
flock -w 120 9
candidate=$(mktemp "$private/.active-base-feed-XXXXXXXX")
trap 'rm -f -- "$candidate"' EXIT
cp "$feed" "$candidate"
"$python" "$tools_dir/refresh_all_shops.py" --active-base --feed "$candidate"
"$python" - "$candidate" "$tools_dir" <<'PY'
from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
sys.path.insert(0, sys.argv[2])
from dashboard_shops import TARGETS
day = datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat()
rows = [r for r in json.loads(Path(sys.argv[1]).read_text())['records'] if r['date'] == day]
if {r['shop_id'] for r in rows} != set(TARGETS):
    raise SystemExit('Not all configured DS available; activation cancelled.')
for row in rows:
    metric = row.get('metrics', {}).get('shift_marked', {})
    if metric.get('basis') != 'direct_shop_scheduled_unique_5d_including_day' or metric.get('value') is None:
        raise SystemExit('Incomplete active base; activation cancelled.')
    print(f"DS {row['shop_id']}: {metric['numerator']} / {metric['denominator']} = {metric['value']}%")
PY
flock -w 120 /opt/courier-analytics/publish.lock "$python" "$tools_dir/publish_dashboard.py" --feed "$candidate"
"$python" - "$candidate" "$feed" "$tools_dir" <<'PY'
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[3])
from enrich_slots import atomic_json
atomic_json(Path(sys.argv[2]), json.loads(Path(sys.argv[1]).read_text()))
Path(sys.argv[2]).chmod(0o644)
folder = Path('/etc/courier-analytics')
folder.mkdir(parents=True, exist_ok=True)
atomic_json(folder/'active-base-enabled.json', {'enabled': True})
PY
echo 'Five-day direct-DS scheduled base published and enabled for future refreshes.'
echo 'Existing timers, plan snapshots, slot-fill scope and Happ/SSH route unchanged.'
