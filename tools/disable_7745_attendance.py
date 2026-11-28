"""Disable DS7745 attendance only, at an idle boundary; no interrupted 1C writes."""
import json
import os
import secrets
import subprocess
import time
from datetime import datetime
from pathlib import Path
from attendance_cases import connect
from prepare_openvpn import private_write
from restart_attendance_when_idle import main as reload_idle,UNIT
CONFIG=Path('/etc/superset-telegram/late-group.json')


def disable():
    original=CONFIG.read_text();config=json.loads(original)
    from attendance_shop_policy import enabled
    enabled(config,7745)
    updated={**config,'disabled_attendance_shops':sorted(set(config.get('disabled_attendance_shops',[]))|{7745})}
    private_write(CONFIG.with_name('late-group.before-disable-7745-'+datetime.now().strftime('%Y%m%dT%H%M%S%f')+'.json'),original)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        rows=db.execute('SELECT id,state,payload FROM cases').fetchall()
        if any(row['state']=='applying' for row in rows):raise ValueError('A write is still in progress; no cases changed')
        for row in rows:
            if json.loads(row['payload'])['shop_id']==7745 and row['state'] not in ('applied','skipped','uncertain','delivery_uncertain','withdrawn'):
                db.execute("UPDATE cases SET state='withdrawn',nonce=?,actor=NULL,result='Attendance disabled by operator',notified=1 WHERE id=?",(secrets.token_hex(4),row['id']))
        if CONFIG.read_text()!=original:raise ValueError('Configuration changed; retry')
        private_write(CONFIG,json.dumps(updated,ensure_ascii=False,indent=2))
        try:db.commit()
        except Exception:
            private_write(CONFIG,original);raise
    print('DS7745 attendance disabled. New proposals, approvals and limit jobs blocked. DS8889 and DS9107 preserved.',flush=True)


def main():
    if os.geteuid()!=0:raise SystemExit('Run on VPS as root')
    os.umask(0o077)
    deadline=time.monotonic()+600
    while True:
        pid=int(subprocess.check_output(['systemctl','show',UNIT,'-p','MainPID','--value'],text=True).strip())
        if pid<=0:
            disable();print('Bot is stopped; configuration saved without starting it.');return
        try:reload_idle(before_stop=disable);return
        except SystemExit as error:
            if not str(error).startswith('Bot is processing a task;') or time.monotonic()>=deadline:raise
            print('Waiting for current bot task to finish; no worker interrupted.',flush=True)
            time.sleep(5)


if __name__=='__main__':main()
