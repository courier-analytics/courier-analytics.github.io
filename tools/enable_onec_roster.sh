#!/usr/bin/env bash
set -euo pipefail
umask 077
scripts=/opt/courier-analytics/dashboard-code/tools
install -m 644 "$scripts/courier-onec-roster.service" /etc/systemd/system/courier-onec-roster.service
install -m 644 "$scripts/courier-onec-roster.timer" /etc/systemd/system/courier-onec-roster.timer
systemctl daemon-reload
# Activate consumption only after native export and all filters are verified.
systemctl start courier-onec-roster.service
/opt/courier-analytics/import-venv/bin/python - "$scripts" <<'PY'
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
sys.path.insert(0,sys.argv[1])
from onec_roster_cache import load
snapshot=load(Path('/opt/courier-analytics/private/onec-rosters/7745.json'),datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat())
print('Verified current 1C roster: DS 7745,',snapshot['count'],'couriers.')
PY
install -d -m 755 /etc/systemd/system/courier-refresh.service.d
cat > /etc/systemd/system/courier-refresh.service.d/zz-onec-roster.conf <<'UNIT'
[Service]
EnvironmentFile=-/etc/courier-analytics/proxy.env
ExecStart=
ExecStart=/usr/bin/flock -n /opt/courier-analytics/refresh.lock /opt/courier-analytics/import-venv/bin/python /opt/courier-analytics/dashboard-code/tools/refresh_all_shops.py --feed /opt/courier-analytics/current-site/data/dashboard.json
ExecStartPost=
ExecStartPost=/usr/bin/flock -n /opt/courier-analytics/publish.lock /opt/courier-analytics/import-venv/bin/python /opt/courier-analytics/dashboard-code/tools/publish_dashboard.py --feed /opt/courier-analytics/current-site/data/dashboard.json
UNIT
systemctl daemon-reload
systemctl enable --now courier-onec-roster.timer
systemctl start courier-refresh.service
systemctl list-timers courier-onec-roster.timer --no-pager
journalctl -u courier-onec-roster.service -n 8 --no-pager
