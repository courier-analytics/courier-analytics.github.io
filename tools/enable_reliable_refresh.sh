#!/usr/bin/env bash
# Keep current HTTPS entries/accounts, refresh today and yesterday, and retry 1C failures.
set -euo pipefail
umask 077
cd /opt/courier-analytics/dashboard-code
[[ $(id -u) == 0 ]] || { echo 'Run on the dashboard VPS as root.'; exit 1; }
install -m 644 tools/courier-onec-roster.service /etc/systemd/system/courier-onec-roster.service
install -m 644 tools/courier-onec-roster.timer /etc/systemd/system/courier-onec-roster.timer
install -d -m 755 /etc/systemd/system/courier-refresh.service.d
cat > /etc/systemd/system/courier-refresh.service.d/zzz-recent-days.conf <<'UNIT'
[Service]
EnvironmentFile=-/etc/courier-analytics/proxy.env
TimeoutStartSec=1200
ExecStart=
ExecStart=/usr/bin/flock -n /opt/courier-analytics/refresh.lock /opt/courier-analytics/import-venv/bin/python /opt/courier-analytics/dashboard-code/tools/refresh_recent_days.py --feed /opt/courier-analytics/current-site/data/dashboard.json
ExecStartPost=
ExecStartPost=/usr/bin/flock -n /opt/courier-analytics/publish.lock /opt/courier-analytics/import-venv/bin/python /opt/courier-analytics/dashboard-code/tools/publish_dashboard.py --feed /opt/courier-analytics/current-site/data/dashboard.json
UNIT
systemctl daemon-reload
systemctl reset-failed courier-onec-roster.service courier-refresh.service
systemctl enable --now courier-onec-roster.timer courier-refresh.timer
if ! systemctl start courier-onec-roster.service; then
  echo 'Fresh 1C export failed. Bounded automatic retries are scheduled; unverified roster will not replace confirmed data.'
fi
systemctl start courier-refresh.service
systemctl start courier-web-data.service
bash tools/update_private_frontend.sh
/opt/courier-analytics/import-venv/bin/python - <<'PY'
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import json,subprocess,sys
base=Path('/opt/courier-analytics')
day=datetime.now(ZoneInfo('Europe/Moscow')).date()
dates={day.isoformat(),(day-timedelta(days=1)).isoformat()}
feed=json.loads((base/'current-site/data/dashboard.json').read_text())
for row in feed['records']:
    if row['shop_id']==7745 and row['date'] in dates:
        print(json.dumps({'date':row['date'],'shop_id':7745,'reported_at':row['reported_at'],'metrics':row['metrics']},ensure_ascii=False,indent=2))
        if row['date']==day.isoformat() and any(row['metrics'].get(key,{}).get('stale_reason')=='planned_booking_missing_from_current_data' or row['metrics'].get(key,{}).get('reason')=='planned_booking_missing_from_current_data' for key in ('planned_attendance','planned_late')):
            print('Some planned facts remain unresolved; saving fresh private evidence.',flush=True)
            outcome=subprocess.run([sys.executable,str(base/'dashboard-code/tools/diagnose_missing_plan.py'),'--date',day.isoformat(),'--shop','7745'])
            if outcome.returncode:print('Additional private evidence collection failed; confirmed values preserved.')
p=base/'private/onec-browser-status.json'
if p.exists():
    state=json.loads(p.read_text())
    print('1C status:',json.dumps({k:state[k] for k in ('authenticated','stage','stage_timeout','roster_verified','roster_check') if k in state},ensure_ascii=False))
PY
