#!/usr/bin/env bash
# Register DS9107 in the live app, refresh, and verify actual observations.
set -euo pipefail
base=/opt/courier-analytics
scripts="$base/dashboard-code/tools"
python="$base/import-venv/bin/python"
[[ $(id -u) == 0 ]] || { echo 'Run on the server as root.'; exit 1; }
test -x "$python"
# Older deployments import TARGETS from current-app; copy only registration into
# that managed tools folder if it is separate from the checked-out source.
"$python" - "$scripts" <<'PY'
from pathlib import Path
import sys,shutil,datetime,ast,os
source=Path(sys.argv[1]);active=Path('/opt/courier-analytics/current-app/tools')
if active.is_dir() and active.resolve()!=source.resolve():
    target=active/'dashboard_shops.py'
    if target.exists():shutil.copy2(target,target.with_suffix('.py.before-9107'))
    shutil.copy2(source/'dashboard_shops.py',target)
# Add routes to the deployed authenticated app without replacing its other code.
app=Path('/opt/courier-dashboard/app/app.py')
if app.exists():
    text=app.read_text();tree=ast.parse(text);lines=text.splitlines(keepends=True)
    node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='FILES' for t in n.targets))
    files=ast.literal_eval(node.value)|{'8889.html','9107.html','dashboard.html','public-details.js'}
    lines[node.lineno-1:node.end_lineno]=['FILES = '+repr(files)+'\n']
    updated=''.join(lines).replace('(7745,5818,4747,8092)','(7745,5818,4747,8092,8889,9107)')
    if updated!=text:
        compile(updated,str(app),'exec')
        shutil.copy2(app,app.with_name('app.py.before-9107-'+datetime.datetime.now().strftime('%Y%m%d%H%M%S')))
        tmp=app.with_suffix('.py.new');tmp.write_text(updated);shutil.copymode(app,tmp);os.replace(tmp,app)
PY
if [[ -f /opt/courier-dashboard/app/app.py ]]; then
    bash "$scripts/update_private_frontend.sh"
    systemctl restart courier-web.service
fi
# Use the existing global locks; do not launch another collector concurrently.
flock -w 180 "$base/refresh.lock" "$python" "$scripts/refresh_all_shops.py" --feed "$base/current-site/data/dashboard.json" > "$base/private/enable-9107-refresh.json"
"$python" - "$base/current-site/data/dashboard.json" <<'PY'
import json,sys
from datetime import datetime
from zoneinfo import ZoneInfo
payload=json.load(open(sys.argv[1]));day=datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat()
rows=[r for r in payload['records'] if r['shop_id']==9107 and r['date']==day]
if len(rows)!=1:raise SystemExit('No verified DS9107 observation; publication stopped. Inspect private/enable-9107-refresh.json')
row=rows[0]
print(json.dumps({'shop_id':9107,'date':day,'reported_at':row['reported_at'],'metrics':row.get('metrics',{})},ensure_ascii=False,indent=2))
PY
flock -w 120 "$base/publish.lock" "$python" "$scripts/publish_dashboard.py" --feed "$base/current-site/data/dashboard.json"
if [[ -f /opt/courier-dashboard/app/app.py ]]; then systemctl start courier-web-data.service; fi
if [[ $(systemctl show courier-medical.service -p LoadState --value) == loaded ]]; then
    systemctl start --no-block courier-medical.service
    echo 'Medical refresh queued separately; missing source rows remain unavailable.'
fi
echo 'DS9107 collection registered. Page: /9107.html. No historical or unavailable metric values were invented.'
