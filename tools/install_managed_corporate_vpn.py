"""Enable/disable a host-routed persistent tunnel without stopping other jobs."""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import socket
import shlex
import stat
import re
import subprocess
from prepare_openvpn import candidate,private_write
from corporate_vpn_session import SETTINGS,USERS,SERVICE,settings

ROOT=Path('/etc/courier-vpn')
TOOLS=Path('/opt/courier-analytics/dashboard-code/tools')


def profile_for_service(profile,addresses,auth):
    config,needs_auth=candidate(profile,addresses,auth)
    lines=[];block=None
    for line in config.splitlines():
        if block:
            lines.append(line)
            if line=='</'+block+'>':block=None
            continue
        if line.startswith('<') and not line.startswith('</'):
            block=line[1:-1];lines.append(line);continue
        args=shlex.split(line,comments=True)
        if args and args[0] in ('dev','dev-type','persist-tun','connect-retry-max'):continue
        lines.append(line)
    return '\n'.join(lines)+'\ndev tun42\ndev-type tun\nconnect-retry-max 3\n',needs_auth


def private_file(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o077:
        raise ValueError('VPN credential/profile owner or permissions invalid')


def external_callers():
    found=[]
    for base in (Path('/opt/courier-contacts'),Path('/opt/courier-handover')):
        if not base.exists():continue
        for folder,dirs,files in os.walk(base):
            dirs[:]=[d for d in dirs if d not in ('venv','.venv','node_modules','.git','private','__pycache__','site-packages') and not d.endswith('-venv')]
            for name in files:
                path=Path(folder)/name
                if path.suffix not in ('.py','.sh') or path.stat().st_size>1048576:continue
                text=path.read_text(errors='replace')
                direct=bool(re.search(r"['\"]openvpn['\"]",text) or re.search(r'^\s*(?:sudo\s+)?openvpn\s',text,re.M))
                lease='shared_vpn_resource' in text and 'acquire(' in text
                if direct or lease:found.append(str(path))
    return found


def disable():
    with USERS.open('a') as users:
        try:fcntl.flock(users,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Collectors are using VPN; rollback deferred. No tunnel stopped.')
        subprocess.run(['systemctl','disable','--now',SERVICE],check=True)
        SETTINGS.unlink(missing_ok=True)
    print('Managed VPN disabled after collectors drained. Next jobs use temporary tunnels. Bot and timers not restarted.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disable',action='store_true')
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run on VPS as root')
    os.umask(0o077)
    if args.disable:return disable()
    if SETTINGS.exists():
        settings()
        print('Managed VPN already configured; no running tunnel restarted.')
        subprocess.run(['systemctl','is-active',SERVICE],check=False)
        return
    callers=external_callers()
    if callers:
        print('Unconverted external VPN callers; no network settings changed:')
        for path in callers:print(path)
        raise SystemExit(1)
    profile=Path('/root/courier-openvpn-tcp.ovpn');auth=Path('/root/courier-openvpn.auth')
    private_file(profile);private_file(auth)
    addresses={'10.210.254.19','10.0.112.18'}
    addresses.update(row[4][0] for row in socket.getaddrinfo('superset.svc.vkusvill.ru',443,socket.AF_INET,socket.SOCK_STREAM))
    if len(addresses)>6 or any(not ipaddress.IPv4Address(a).is_private for a in addresses):
        raise SystemExit('Unexpected Superset address; no VPN configuration changed')
    config,needs_auth=profile_for_service(profile.read_text(),sorted(addresses),auth)
    ROOT.mkdir(mode=0o700,exist_ok=True)
    ROOT.chmod(0o700)
    unit=Path('/etc/systemd/system')/SERVICE
    if unit.exists() and ('ExecStart=/usr/bin/python3 '+str(TOOLS/'managed_corporate_vpn.py')) not in unit.read_text():
        raise SystemExit('Unrecognized existing managed service; no configuration changed')
    private_write(ROOT/'client.conf',config)
    unit.write_text('[Unit]\nDescription=Shared corporate VPN for courier collectors\nWants=network-online.target\nAfter=network-online.target\nStartLimitIntervalSec=0\n\n[Service]\nType=simple\nUser=root\nUMask=0077\nExecStart=/usr/bin/python3 '+str(TOOLS/'managed_corporate_vpn.py')+'\nRestart=on-failure\nRestartSec=20\nRestartPreventExitStatus=78\nKillMode=mixed\nTimeoutStopSec=30\n\n[Install]\nWantedBy=multi-user.target\n')
    unit.chmod(0o644)
    rotation=Path('/etc/logrotate.d/courier-corporate-vpn')
    if not rotation.exists():
        rotation.write_text('/var/log/courier-corporate-vpn/private.log {\n daily\n maxsize 10M\n rotate 7\n missingok\n notifempty\n compress\n copytruncate\n}\n')
        rotation.chmod(0o644)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    # Mode is selected before starting: new clients defer while an older
    # temporary session finishes. They cannot create a competing tunnel.
    private_write(SETTINGS,json.dumps({'interface':'tun42','addresses':sorted(addresses)}))
    subprocess.run(['systemctl','enable',SERVICE],check=True)
    subprocess.run(['systemctl','start','--no-block',SERVICE],check=True)
    print('Managed VPN transition started. Existing jobs are not stopped; service waits for the old VPN lease. No default route or system DNS changes. Bot and schedules unchanged.')
    print('Check journalctl -u '+SERVICE+' -n 20 --no-pager for connection confirmation.')


if __name__=='__main__':main()
