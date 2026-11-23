#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $(id -u) == 0 ]] || { echo 'Run on server as root'; exit 1; }
cd /opt/courier-analytics/dashboard-code
python=/opt/courier-analytics/import-venv/bin/python
"$python" -m py_compile tools/attendance_bot.py tools/matryoshka_command_handler.py tools/matryoshka_command_report.py
systemctl stop courier-attendance-bot.service courier-matryoshka-commands.service
trap 'systemctl stop courier-attendance-bot.service; systemctl start courier-matryoshka-commands.service' ERR
"$python" - <<'PY'
import sys,sqlite3,json
from datetime import datetime
from pathlib import Path
sys.path.insert(0,'tools')
from attendance_cases import connect
from matryoshka_command_handler import Handler
from late_bot_group import load_token,api
root=Path('/opt/courier-analytics/private')
backup=root/('telegram-migration-'+datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir(mode=0o700)
for path in (root/'attendance-bot/cases.sqlite3',root/'matryoshka-commands.sqlite3'):
 if path.exists():
  with sqlite3.connect(path) as source,sqlite3.connect(backup/path.name) as target:source.backup(target)
token=load_token();me=api(token,'getMe')
if api(token,'getWebhookInfo').get('url'):raise RuntimeError('Webhook present; migration stopped')
handler=Handler(token,me['username'])
with connect() as db:
 if db.execute("SELECT count(*) FROM cases WHERE state='applying'").fetchone()[0]:raise RuntimeError('Unresolved write; inspect before migration')
 old=handler.db.execute("SELECT value FROM state WHERE key='offset'").fetchone()
 current=db.execute("SELECT value FROM meta WHERE key='telegram_offset'").fetchone()
 offset=max(int(old[0]) if old else 0,int(current[0]) if current else 0)
 db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('telegram_offset',?)",(str(offset),))
print('Private database backups saved. Shared receiver validated.')
PY
systemctl reset-failed courier-attendance-bot.service
systemctl start courier-attendance-bot.service
sleep 3
systemctl is-active --quiet courier-attendance-bot.service
systemctl disable courier-matryoshka-commands.service
trap - ERR
systemctl status courier-attendance-bot.service --no-pager --lines=5
printf '%s\n' 'Single receiver enabled for both groups; Matryoshka collection timer unchanged.'
