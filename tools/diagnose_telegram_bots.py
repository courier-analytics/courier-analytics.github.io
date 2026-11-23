"""Read-only Telegram/worker health. Never consumes updates or sends messages."""
import json,sqlite3,subprocess
from pathlib import Path
from collections import Counter
from late_bot_group import load_token,api
BASE=Path('/opt/courier-analytics/private')

def local():
    for unit in ('courier-attendance-bot.service','courier-matryoshka.service','courier-matryoshka.timer'):
        r=subprocess.run(['systemctl','show',unit,'-p','ActiveState','-p','SubState','-p','Result','-p','ExecMainStatus','-p','NRestarts','-p','NextElapseUSecRealtime'],capture_output=True,text=True)
        print(unit, r.stdout.strip().replace('\n','; '))
    r=subprocess.run(['ps','-C','openvpn','-o','pid=,etimes=,comm='],capture_output=True,text=True)
    print('VPN processes (PID, age seconds, name):',r.stdout.strip() or 'none')
    for filename,table in [('attendance-bot/cases.sqlite3','cases'),('matryoshka-deliveries.sqlite3','deliveries')]:
        path=BASE/filename
        if not path.exists():print(filename,'absent');continue
        try:
            with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
                column='state' if table=='cases' else 'status'
                print(filename,json.dumps(dict(db.execute(f'SELECT {column},count(*) FROM {table} GROUP BY {column}').fetchall())))
                if table=='cases':
                    print('Bot heartbeat:',json.dumps(dict(db.execute("SELECT key,value FROM meta WHERE key IN ('last_loop','last_source_success','last_source_error')").fetchall())))
        except sqlite3.Error as e:print(filename,'read error:',type(e).__name__)
    path=BASE/'matryoshka-monitor.json'
    if path.exists():
        data=json.loads(path.read_text());print('Matryoshka source:',json.dumps({'observed_at':data.get('observed_at'),'participants':len(data.get('participants',[]))}))
    log=BASE/'attendance-bot/worker.log'
    if log.exists():
        print('Recent 1C worker checkpoints:')
        for line in log.read_text(errors='replace').splitlines()[-60:]:
            if '1C courier study: ' in line:
                try:
                    value=json.loads(line.split('1C courier study: ',1)[1]);print(json.dumps({k:value.get(k) for k in ('shop_id','stage','card_opened','limit_verified','record_edited')}))
                except ValueError:pass
            elif any(text in line for text in ('VPN connected;','Another OpenVPN','An OpenVPN','Temporary VPN stopped;','No automatic retry','1C browser operation failed','not verified;','Invalid','failed:','failed;')):
                # These fixed diagnostic lines do not contain headers/tokens.
                if not any(text in line.lower() for text in ('token','password','authorization')):print(line[:250])

def telegram():
    try:
        token=load_token();me=api(token,'getMe');webhook=api(token,'getWebhookInfo')
        print('Telegram:',json.dumps({'reachable':True,'bot_id':me['id'],'username':me.get('username'),'webhook_present':bool(webhook.get('url')),'pending_updates':webhook.get('pending_update_count')}))
        for file in ('test-group.json','late-group.json'):
            path=Path('/etc/superset-telegram')/file
            if not path.exists():print(file,'absent');continue
            config=json.loads(path.read_text())
            try:
                chat=api(token,'getChat',{'chat_id':config['chat_id']})
                membership=api(token,'getChatMember',{'chat_id':config['chat_id'],'user_id':me['id']})
                print(file,json.dumps({'chat_id':chat['id'],'title':chat.get('title'),'bot_status':membership.get('status'),'can_send_messages':membership.get('can_send_messages')},ensure_ascii=False))
            except RuntimeError as error:print(file,str(error))
    except (OSError,ValueError,KeyError,RuntimeError) as error:print('Telegram diagnostic failed:',str(error) if isinstance(error,RuntimeError) else type(error).__name__)

def journals():
    for unit in ('courier-attendance-bot','courier-matryoshka'):
        print('Recent journal:',unit)
        r=subprocess.run(['journalctl','-u',unit,'-n','18','--no-pager','-o','cat'],capture_output=True,text=True)
        # Known applications emit only sanitized status, never credentials.
        for line in r.stdout.splitlines():
            if not any(term in line.lower() for term in ('access_token','authorization:','bot_token','password')):print(line[:600])

if __name__=='__main__':
    print('READ-ONLY DIAGNOSTIC. No updates consumed, no Telegram sends, no 1C edits.')
    local();telegram();journals()
