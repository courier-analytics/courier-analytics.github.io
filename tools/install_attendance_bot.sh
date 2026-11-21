#!/usr/bin/env bash
set -euo pipefail
umask 077
base=/opt/courier-analytics
scripts="$base/dashboard-code/tools"
[[ $(id -u) == 0 ]] || { echo 'Run on the server as root.'; exit 1; }
"$base/import-venv/bin/python" - "$@" <<'PY'
import json,sys,os
from pathlib import Path
from datetime import date
sys.path.insert(0,'/opt/courier-analytics/dashboard-code/tools')
from late_bot_group import load_token,api
from prepare_openvpn import private_write
from attendance_cases import connect
path=Path('/etc/superset-telegram/late-group.json')
if path.stat().st_mode&0o077:raise SystemExit('Group configuration must be private')
config=json.loads(path.read_text());token=load_token()
if not config.get('human_review_required') or config.get('automatic_limit_changes') is not False or not config.get('approver_ids'):raise SystemExit('Per-case responsible-person approval must be configured')
if api(token,'getWebhookInfo').get('url'):raise SystemExit('Existing Telegram webhook detected; preserve it and integrate with its owner first')
if api(token,'getMe')['id']!=config['bot_id']:raise SystemExit('Bot identity mismatch')
chat=api(token,'getChat',{'chat_id':config['chat_id']})
if chat.get('title','').casefold()!='опоздавшие':raise SystemExit('Group identity mismatch')
for argument in sys.argv[1:]:
    day,shop,courier=argument.split(':');date.fromisoformat(day)
    if int(shop) not in (8889,7745,9107) or not courier.isdigit():raise SystemExit('Invalid skipped case')
    item={'date':day,'shop_id':int(shop),'courier_id':courier}
    config.setdefault('ignored_cases',[])
    if item not in config['ignored_cases']:config['ignored_cases'].append(item)
private_write(path,json.dumps(config,ensure_ascii=False,indent=2))
with connect() as db:
    # Fail closed after restarts: an in-flight write is never resubmitted.
    db.execute("UPDATE cases SET state='uncertain',notified=0 WHERE state='applying'")
print('Group and human reviewers configured; 1C writes require an individual Apply button.')
PY
install -d -m 755 /etc/systemd/system
cat > /etc/systemd/system/courier-attendance-bot.service <<'UNIT'
[Unit]
Description=Attendance review and individually approved courier limits
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=600
StartLimitBurst=5
[Service]
Type=simple
User=root
UMask=0077
EnvironmentFile=-/etc/courier-analytics/proxy.env
ExecStart=/opt/courier-analytics/import-venv/bin/python -u /opt/courier-analytics/dashboard-code/tools/attendance_bot.py
Restart=on-failure
RestartSec=30
RestartPreventExitStatus=78
KillMode=control-group
TimeoutStopSec=20
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now courier-attendance-bot.service
systemctl status courier-attendance-bot.service --no-pager --lines=8
echo 'Bot started. Reports refresh every 2 minutes; only configured human reviewers can approve a case.'
