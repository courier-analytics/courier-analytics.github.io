"""Observe actual attendance progress; bounded VPN recovery, no 1C writes or bot restarts."""
import fcntl,json,subprocess,time,sqlite3
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from prepare_openvpn import private_write
from attendance_shop_policy import enabled

ROOT=Path('/opt/courier-analytics/private/reliability')
STATE=ROOT/'state.json'
ALERTS=Path('/etc/superset-telegram/technical-alerts.json')
MODE=Path('/etc/courier-vpn/shared.json')
VPN='courier-corporate-vpn.service'
BOT='courier-attendance-bot.service'
TZ=ZoneInfo('Europe/Moscow')
LABELS={'vpn_unavailable':'Нет готового VPN-маршрута к 1С.', 'bot_not_running':'Процесс бота опозданий не работает.',
        'receiver_stale':'Цикл бота не обновлялся более 3 минут.', 'source_stale':'Нет успешного обновления КПС более 10 минут.',
        'queue_overdue':'Есть случаи, ожидающие обработки более 15 минут с начала наблюдения.',
        'reads_held':'Есть случаи, где исчерпаны попытки чтения 1С; нужна проверка.',
        'result_unconfirmed':'Есть случаи с неподтверждённым результатом изменения или отправки; нужна ручная проверка.',
        'health_unavailable':'Не удалось прочитать состояние бота или служб.'}


def run(args):
    try:
        result=subprocess.run(args,capture_output=True,text=True,timeout=8)
        return result.returncode,result.stdout
    except (OSError,subprocess.TimeoutExpired):return -1,''


def service(unit):
    code,text=run(['systemctl','show',unit,'-p','ActiveState','-p','SubState','-p','ExecMainStatus'])
    if code:raise ValueError('Service state unavailable')
    return dict(line.split('=',1) for line in text.splitlines() if '=' in line)


def age(value,now):
    if not value:return float('inf')
    moment=datetime.fromisoformat(value)
    if moment.tzinfo is None:raise ValueError('Timestamp timezone missing')
    delta=now-moment.timestamp()
    return max(0,delta) if delta>=-120 else float('inf')


def retry_allowed(attempts,now):
    recent=[t for t in attempts if 0<=now-t<3600]
    return len(recent)<3 and (not recent or now-max(recent)>=300)


def collect(state,now):
    config=json.loads(Path('/etc/superset-telegram/late-group.json').read_text())
    bot=service(BOT);vpn=service(VPN);issues=[]
    managed=MODE.exists()
    if managed:
        code,text=run(['ip','-j','route','get','10.210.254.19'])
        try:routes=json.loads(text) if code==0 else []
        except ValueError:routes=[]
        if vpn.get('ActiveState')!='active' or len(routes)!=1 or routes[0].get('dev')!='tun42':issues.append('vpn_unavailable')
    if bot.get('ActiveState')!='active':issues.append('bot_not_running')
    path=Path('/opt/courier-analytics/private/attendance-bot/cases.sqlite3')
    pending={};counts={};previous=state.get('pending_since',{})
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
        meta=dict(db.execute("SELECT key,value FROM meta WHERE key IN ('last_loop','last_source_success')"))
        if bot.get('ActiveState')=='active' and age(meta.get('last_loop'),now)>180:issues.append('receiver_stale')
        if age(meta.get('last_source_success'),now)>600:issues.append('source_stale')
        today=datetime.fromtimestamp(now,TZ).date().isoformat()
        for identity,payload,status,attempts in db.execute('SELECT id,payload,state,read_attempts FROM cases'):
            p=json.loads(payload)
            if p.get('date')!=today or not enabled(config,p['shop_id']):continue
            counts[status]=counts.get(status,0)+1
            if status=='held' and attempts>=3:issues.append('reads_held')
            if status in ('uncertain','delivery_uncertain'):issues.append('result_unconfirmed')
            if status in ('need_limit','reading','ready'):
                pending[identity]=previous.get(identity,now)
    if any(now-t>=900 for t in pending.values()):issues.append('queue_overdue')
    state['pending_since']=pending
    return sorted(set(issues)),{'bot':bot,'vpn':vpn,'managed_vpn':managed,'today_states':counts}


def notify(state,issues,now):
    if not ALERTS.exists():return
    config=json.loads(ALERTS.read_text())
    if config.get('enabled') is not True:return
    signature='|'.join(issues) if issues else 'recovered'
    previous=state.get('notice_signature')
    if signature==previous or (not issues and previous is None):return
    if type(config.get('chat_id')) is not int or config['chat_id']>=0:raise ValueError('Invalid technical group')
    text=('Сбой работы сервисов курьеров:\n'+'\n'.join('• '+LABELS[issue] for issue in issues)) if issues else 'Восстановление: проверки VPN, бота, свежести КПС и очереди проходят; случаев с исчерпанными попытками чтения или неподтверждённым результатом за сегодня на включённых ДС не обнаружено.'
    text+='\nПроверка: '+datetime.fromtimestamp(now,TZ).strftime('%d.%m.%Y %H:%M МСК')
    # Claim before network send. Unknown delivery is never automatically repeated.
    state.update(notice_signature=signature,notice_delivery='sending');private_write(STATE,json.dumps(state))
    from late_bot_group import api,load_token
    try:
        result=api(load_token(),'sendMessage',{'chat_id':config['chat_id'],'text':text})
        if type(result.get('message_id')) is not int:raise RuntimeError('Delivery unconfirmed')
        state['notice_delivery']='sent'
    except RuntimeError:
        state['notice_delivery']='uncertain'
        print('Technical notice delivery unconfirmed; no automatic duplicate send',flush=True)
    private_write(STATE,json.dumps(state))


def main():
    import os
    os.umask(0o077);ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (ROOT/'watch.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        state=json.loads(STATE.read_text()) if STATE.exists() else {}
        now=time.time()
        try:issues,details=collect(state,now)
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):issues=['health_unavailable'];details={}
        if details.get('managed_vpn') and details.get('vpn',{}).get('ActiveState')=='failed' and retry_allowed(state.get('vpn_attempts',[]),now):
            state['vpn_attempts']=[t for t in state.get('vpn_attempts',[]) if 0<=now-t<3600]+[now]
            private_write(STATE,json.dumps(state))
            code,_=run(['systemctl','start','--no-block',VPN])
            print('Bounded VPN recovery requested; accepted='+str(code==0),flush=True)
        state.update(checked_at=datetime.fromtimestamp(now,TZ).isoformat(),issues=issues,details=details)
        private_write(STATE,json.dumps(state))
        print('Reliability check:',','.join(issues) or 'checks_passed',flush=True)
        try:notify(state,issues,now)
        except (OSError,ValueError,KeyError,TypeError,RuntimeError):print('Technical alerts unavailable; private health report saved',flush=True)


if __name__=='__main__':main()
