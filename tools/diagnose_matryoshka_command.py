"""Diagnose command rendering and shared receiver without consuming Telegram updates."""
import json
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from matryoshka_command_report import command,render
ROOT=Path('/opt/courier-analytics/private')

def main():
    text='/matreshka_idle@vv_services_reports_bot'
    output={'command_recognized':command(text,'vv_services_reports_bot') is not None}
    config=json.loads(Path('/etc/superset-telegram/test-group.json').read_text())
    output['allowed_chat_id']=config.get('chat_id')
    marker=Path('/opt/courier-matryoshka-commands/installed-at')
    output['installation_marker_exists']=marker.exists()
    try:
        snapshot=json.loads((ROOT/'matryoshka-monitor.json').read_text())
        output['source_observed_at']=snapshot.get('observed_at')
        roster_path=Path('/opt/courier-contacts/connected/all.json')
        rosters=json.loads(roster_path.read_text()) if roster_path.exists() else {}
        pages=render(snapshot,'',datetime.now(ZoneInfo('Europe/Moscow')),rosters,idle_days=3)
        output['render']={'ok':True,'pages':len(pages),'max_characters':max(map(len,pages))}
    except Exception as error:
        known={'unverified','invalid_time','invalid_identity','unverified_participant','invalid_participant','invalid_shop','last_delivery_after_snapshot'}
        output['render']={'ok':False,'error':type(error).__name__,'reason':str(error) if str(error) in known else 'private_details_hidden'}
    path=ROOT/'matryoshka-commands.sqlite3'
    if path.exists():
        with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
            output['reply_states']=dict(db.execute('SELECT status,count(*) FROM updates GROUP BY status'))
    path=ROOT/'attendance-bot/cases.sqlite3'
    if path.exists():
        with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
            output['receiver_heartbeat']=dict(db.execute("SELECT key,value FROM meta WHERE key IN ('last_loop','last_source_success','telegram_offset')"))
    result=subprocess.run(['systemctl','show','courier-attendance-bot.service','-p','ActiveState','-p','SubState','-p','ExecMainStatus','-p','NRestarts'],capture_output=True,text=True)
    output['receiver_service']=result.stdout.splitlines()
    print(json.dumps(output,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
