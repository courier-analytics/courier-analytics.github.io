"""Install passive health checks and bounded recovery of failed VPN only."""
import argparse,json,os,subprocess
from pathlib import Path
from late_bot_group import api,load_token,chat_from_link
from prepare_openvpn import private_write


def main():
    p=argparse.ArgumentParser();p.add_argument('--technical-message-link');args=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run on VPS as root')
    os.umask(0o077)
    if args.technical_message_link:
        chat_id=chat_from_link(args.technical_message_link);token=load_token()
        config=json.loads(Path('/etc/superset-telegram/late-group.json').read_text())
        me=api(token,'getMe');chat=api(token,'getChat',{'chat_id':chat_id})
        if me.get('id')!=config.get('bot_id') or chat.get('id')!=chat_id or chat.get('type') not in ('group','supergroup'):raise ValueError('Technical recipient identity not verified')
        membership=api(token,'getChatMember',{'chat_id':chat_id,'user_id':me['id']})
        if membership.get('status') not in ('member','administrator','creator'):raise ValueError('Add bot to the technical group before configuring alerts')
        private_write(Path('/etc/superset-telegram/technical-alerts.json'),json.dumps({'enabled':True,'chat_id':chat_id,'bot_id':me['id']}))
    root=Path('/etc/systemd/system')
    (root/'courier-reliability-watch.service').write_text('[Unit]\nDescription=Courier health and bounded VPN recovery\n[Service]\nType=oneshot\nUser=root\nUMask=0077\nTimeoutStartSec=90\nExecStart=/opt/courier-analytics/import-venv/bin/python /opt/courier-analytics/dashboard-code/tools/courier_reliability.py\n')
    (root/'courier-reliability-watch.timer').write_text('[Unit]\nDescription=Observe courier health every minute\n[Timer]\nOnBootSec=60\nOnUnitInactiveSec=60\n[Install]\nWantedBy=timers.target\n')
    for name in ('courier-reliability-watch.service','courier-reliability-watch.timer'):(root/name).chmod(0o644)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now','courier-reliability-watch.timer'],check=True)
    subprocess.run(['systemctl','start','--no-block','courier-reliability-watch.service'],check=True)
    print('Reliability checks installed. Failed VPN: max 3 start attempts/hour, at least 5 minutes apart. Active VPN and bot not restarted. DS7745 policy preserved.')
    print('Technical group alerts: '+('configured' if Path('/etc/superset-telegram/technical-alerts.json').exists() else 'not configured; health reports remain private on server'))


if __name__=='__main__':main()
