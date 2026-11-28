"""Bind DS8353 attendance to the explicitly requested group, at a safe idle boundary."""
import json,os,subprocess,time
from pathlib import Path
from datetime import datetime
from attendance_review import TZ
from prepare_openvpn import private_write
from late_bot_group import api,load_token
from restart_attendance_when_idle import main as reload_idle,UNIT
CONFIG=Path('/etc/superset-telegram/late-group.json')
CHAT=-1004365044892


def updated_config(config):
    routes=config.get('shop_routes',{})
    if routes.get('8353',CHAT)!=CHAT:raise ValueError('Different DS8353 recipient already configured')
    disabled=sorted((set(config.get('disabled_attendance_shops',[]))|{7745})-{8353})
    return {**config,'attendance_8353_enabled':True,'disabled_attendance_shops':disabled,
            'shops':sorted(set(config.get('shops',[8889,7745,9107]))|{8353}),
            'shop_routes':{**routes,'8353':CHAT},
            'member_approval_shops':sorted(set(config.get('member_approval_shops',[]))|{8353})}


def verify():
    config=json.loads(CONFIG.read_text());updated_config(config)
    token=load_token();bot=api(token,'getMe');chat=api(token,'getChat',{'chat_id':CHAT})
    if bot.get('id')!=config.get('bot_id') or chat.get('id')!=CHAT or chat.get('type') not in ('group','supergroup'):raise ValueError('Bot/group identity not confirmed')
    member=api(token,'getChatMember',{'chat_id':CHAT,'user_id':bot['id']})
    if member.get('status') not in ('administrator','creator'):raise ValueError('Bot must be administrator to verify group member decisions')
    from audit_sources import audit
    from proxy_config import configured_proxy
    day=datetime.now(TZ).date().isoformat()
    source_token=json.loads(Path('/root/curator-session.json').read_text())['token']
    folder=Path('/opt/courier-analytics/private/attendance-8353-preflight')/day
    result=audit(day,source_token,configured_proxy(),folder,extra_details=False,targets=(8353,))
    if not any(s.get('shop_id')==8353 and s.get('scope_verified') is True for s in result['shops']):raise ValueError('DS8353 source scope not verified; configuration unchanged')
    print('DS8353 source and Telegram recipient verified. Waiting for safe bot reload.',flush=True)


def enable():
    original=CONFIG.read_text();updated=updated_config(json.loads(original))
    private_write(CONFIG.with_name('late-group.before-8353-'+datetime.now().strftime('%Y%m%dT%H%M%S%f')+'.json'),original)
    private_write(CONFIG,json.dumps(updated,ensure_ascii=False,indent=2))
    print('DS8353 enabled: >15 to 60 minutes caps bike=3/car=8; >60 minutes cap=1. Never increase smaller pools. Current group members may Apply/Skip. DS7745 disabled policy and other shops preserved.',flush=True)


def main():
    if os.geteuid()!=0:raise SystemExit('Run on VPS as root')
    os.umask(0o077);verify();deadline=time.monotonic()+600
    while True:
        pid=int(subprocess.check_output(['systemctl','show',UNIT,'-p','MainPID','--value'],text=True).strip())
        if pid<=0:enable();print('Bot is stopped; configuration saved without starting it.');return
        try:reload_idle(before_stop=enable);return
        except SystemExit as error:
            if not str(error).startswith('Bot is processing a task;') or time.monotonic()>=deadline:raise
            print('Current task continues; waiting for idle boundary',flush=True);time.sleep(5)


if __name__=='__main__':main()
