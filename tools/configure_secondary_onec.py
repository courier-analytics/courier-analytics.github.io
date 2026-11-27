"""Privately provision and verify a second read-only 1C account before routing jobs."""
import argparse
from datetime import datetime,timezone
import fcntl
import getpass
import json
import os
from pathlib import Path
import subprocess
from onec_accounts import SECONDARY,ENABLED,SECONDARY_LOCK,secondary_credentials
from onec_browser import load_credentials,CREDENTIALS
from prepare_openvpn import private_write

ROOT=Path('/opt/courier-analytics/private')
TOOLS=Path('/opt/courier-analytics/dashboard-code/tools')


def save_secondary(username,password):
    if not username.strip() or not password or any(ord(c)<32 for c in username+password):raise ValueError('Empty credentials or control characters rejected')
    primary=load_credentials(CREDENTIALS)
    if username.strip().casefold()==primary['username'].strip().casefold():raise ValueError('Provide a different 1C account; primary credentials unchanged')
    private_write(SECONDARY,json.dumps({'username':username,'password':password}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disable',action='store_true')
    parser.add_argument('--replace',action='store_true',help='Replace saved secondary credentials only while disabled')
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run on VPS as root')
    os.umask(0o077)
    if args.disable:
        ENABLED.unlink(missing_ok=True)
        print('Future pool reads use primary account. Existing tasks are not interrupted; credentials preserved.')
        return
    if ENABLED.exists():
        if args.replace:raise SystemExit('Disable secondary routing before replacing its credentials')
        from onec_accounts import pool_account
        pool_account()
        print('Secondary account already enabled for read-only pools; no jobs restarted.')
        return
    if args.replace or not SECONDARY.exists():
        save_secondary(getpass.getpass('Second 1C username (hidden): '),getpass.getpass('Second 1C password (hidden): '))
    secondary_credentials()
    snapshot=json.loads((ROOT/'matryoshka-monitor.json').read_text())
    if snapshot.get('verified') is not True:raise SystemExit('Verified participants unavailable; account saved but routing unchanged')
    people=[p for p in snapshot.get('participants',[]) if str(p.get('courier_id','')).isdigit() and p.get('name') and str(p.get('last_shop')) in ('7745','8889','9107')]
    if not people:raise SystemExit('No verified participant for read-only test; routing unchanged')
    person=people[0]
    with SECONDARY_LOCK.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Secondary account busy; routing unchanged')
        print('Checking second account login and one courier limit. No 1C values will be changed.',flush=True)
        status=ROOT/'onec-secondary/onec-browser-status.json'
        before=datetime.now(timezone.utc).timestamp()
        result=subprocess.run(['/opt/courier-analytics/onec-venv/bin/python',str(TOOLS/'probe_powerbi_vpn.py'),'--address','10.210.254.19','--onec-account','secondary','--onec-login','--onec-courier-shop',str(person['last_shop']),'--onec-courier-name',person['name'],'--onec-pool-id',str(person['courier_id'])],timeout=330)
        if result.returncode!=0 or not status.exists() or status.stat().st_mtime<before:
            raise SystemExit('Secondary account test not confirmed; primary routing preserved. Credentials remain private for another test.')
        data=json.loads(status.read_text())
        if data.get('authenticated') is not True or data.get('pool_read') is not True:
            raise SystemExit('Login or verified limit read missing; routing unchanged')
        ENABLED.parent.mkdir(mode=0o700,exist_ok=True)
        private_write(ENABLED,json.dumps({'pool_reads':True,'verified_at':datetime.now(timezone.utc).isoformat()}))
    print('Secondary 1C account verified and enabled for pool reads. Primary account and attendance writes unchanged. No bot restart required.')


if __name__=='__main__':main()
