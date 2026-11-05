#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/courier-analytics/dashboard-code
[[ $(id -u) == 0 ]] || { echo 'Run on the dashboard VPS as root.'; exit 1; }
install -d -m 755 /etc/courier-analytics
/opt/courier-analytics/import-venv/bin/python - "$@" <<'PY'
import sys,json,re
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
sys.path.insert(0,'tools')
from prepare_openvpn import private_write
path=Path('/etc/courier-analytics/training.json')
config=json.loads(path.read_text()) if path.exists() else {'start_date':'2026-11-05'}
if len(sys.argv)>2:raise SystemExit('Pass one Google Sheets URL.')
if len(sys.argv)==2:
    link=urlsplit(sys.argv[1])
    match=re.fullmatch(r'/spreadsheets/d/([A-Za-z0-9_-]+)/(?:edit)?/?',link.path)
    query=parse_qs(link.query);fragment=parse_qs(link.fragment)
    gid=(query.get('gid') or fragment.get('gid') or [''])[0]
    if link.scheme!='https' or link.netloc!='docs.google.com' or not match or not gid.isdigit():
        raise SystemExit('Pass the HTTPS Google Sheets link including gid.')
    config.update(spreadsheet_id=match.group(1),gid=gid)
if not config.get('spreadsheet_id') or not str(config.get('gid','')).isdigit():
    raise SystemExit('First setup requires the Google Sheets link as an argument.')
private_write(path,json.dumps(config))
print('Automatic training metric enabled; previous manual history retained.')
PY
install -m 644 tools/private_web/app.py /opt/courier-dashboard/app/app.py
bash tools/update_private_frontend.sh
systemctl restart courier-web.service
systemctl restart courier-refresh.service
systemctl start courier-web-data.service
/opt/courier-analytics/import-venv/bin/python - <<'PY'
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
day=datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat()
feed=json.loads(Path('/opt/courier-analytics/current-site/data/dashboard.json').read_text())
row=next(r for r in feed['records'] if r['shop_id']==7745 and r['date']==day)
print(json.dumps({'date':day,'shop_id':7745,'training':row['metrics'].get('training')},ensure_ascii=False,indent=2))
PY
