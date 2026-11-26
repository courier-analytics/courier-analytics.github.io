"""Install explicit busy deferrals; do not stop, restart, or start any running job."""
from pathlib import Path
from datetime import datetime,timezone
import os
import subprocess
import shutil


def main():
    if os.geteuid()!=0:raise SystemExit('Run on VPS as root')
    root=Path('/opt/courier-analytics/dashboard-code/tools')
    units=['courier-medical.service','courier-refresh.service','courier-matryoshka-pools.service']
    refresh=subprocess.check_output(['systemctl','show','courier-refresh.service','-p','ExecStart','--value'],text=True)
    wrapper=str(root/'refresh_when_available.sh')
    if wrapper not in refresh and not all(part in refresh for part in ('/usr/bin/flock','/opt/courier-analytics/refresh.lock',str(root/'refresh_recent_days.py'),'--feed /opt/courier-analytics/current-site/data/dashboard.json')):
        raise SystemExit('Unexpected refresh command: no service configuration changed')
    backup=Path('/opt/courier-analytics/private')/('contention-backup-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    backup.mkdir(mode=0o700,parents=True)
    for unit in units:
        folder=Path('/etc/systemd/system')/(unit+'.d')
        folder.mkdir(exist_ok=True)
        target=folder/'contention-deferral.conf'
        if target.exists():shutil.copy2(target,backup/(unit+'.conf'))
        content='[Service]\nSuccessExitStatus=75\n'
        if unit=='courier-refresh.service':content+='ExecStart=\nExecStart=/bin/bash '+wrapper+'\n'
        target.write_text(content)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    print('Busy deferrals installed. Running jobs and timer schedules unchanged. Exit 75 means skipped due to contention, not a fresh successful collection. Previous failure states retained.')
    subprocess.run(['systemctl','show',*units,'-p','Id','-p','SuccessExitStatus'],check=True)


if __name__=='__main__':main()
