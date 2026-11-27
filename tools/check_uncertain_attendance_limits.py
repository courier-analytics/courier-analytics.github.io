"""Re-read uncertain case limits; never edit 1C or resolve/retry an attendance write."""
import argparse
from datetime import datetime
import fcntl
import json
from pathlib import Path
import sqlite3
import subprocess
import time
from attendance_review import TZ
from onec_accounts import pool_account,SECONDARY_LOCK
from prepare_openvpn import private_write
ROOT=Path('/opt/courier-analytics/private')


def comparison(current,before,target):
    if current==target:return 'matches_target_but_write_attribution_not_proven'
    if current==before:return 'matches_previous_limit_no_retry_authorized'
    return 'different_limit_requires_review'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=6,choices=range(1,11))
    args=parser.parse_args()
    if pool_account()[0]!='secondary':raise SystemExit('Verified secondary account required; no reads started')
    day=datetime.now(TZ).date().isoformat()
    with sqlite3.connect('file:'+str(ROOT/'attendance-bot/cases.sqlite3')+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        rows=[dict(row) for row in db.execute("SELECT id,payload,current_limit,target_limit FROM cases WHERE state='uncertain' ORDER BY rowid") if json.loads(row['payload']).get('date')==day][:args.limit]
    folder=ROOT/'attendance-limit-checks'/datetime.now(TZ).strftime('%Y%m%dT%H%M%S%f')
    folder.mkdir(mode=0o700,parents=True)
    report={'date':day,'cases':[],'writes_performed':False,'case_states_changed':False}
    with SECONDARY_LOCK.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Secondary account busy; no checks started')
        for case in rows:
            p=json.loads(case['payload']);identity=p['courier_id']
            if not isinstance(identity,str) or not identity.isdigit() or p['shop_id'] not in (7745,8889,9107):raise ValueError('Invalid case identity')
            start=time.time()
            output={'courier_id':identity,'shop':p['shop_id'],'previous_limit':case['current_limit'],'target_limit':case['target_limit'],'verified_read':False}
            command=['/opt/courier-analytics/onec-venv/bin/python','/opt/courier-analytics/dashboard-code/tools/probe_powerbi_vpn.py','--address','10.210.254.19','--onec-account','secondary','--onec-login','--onec-courier-shop',str(p['shop_id']),'--onec-courier-name',p['name'],'--onec-pool-id',identity]
            try:
                result=subprocess.run(command,capture_output=True,text=True,timeout=300)
                private_write(folder/(case['id']+'.log'),result.stdout+'\n'+result.stderr)
                cache=json.loads((ROOT/'matryoshka-pools.json').read_text()).get(identity,{})
                observed=datetime.fromisoformat(cache['observed_at']).timestamp() if cache.get('observed_at') else 0
                if result.returncode==0 and cache.get('verified') is True and type(cache.get('limit')) is int and start<=observed<=time.time()+120:
                    output.update(verified_read=True,current_limit=cache['limit'],comparison=comparison(cache['limit'],case['current_limit'],case['target_limit']))
                else:output['reason']='read_not_confirmed'
            except (OSError,ValueError,subprocess.TimeoutExpired):output['reason']='read_failed_details_private'
            output['elapsed_seconds']=round(time.time()-start,2)
            report['cases'].append(output)
            private_write(folder/'report.json',json.dumps(report,ensure_ascii=False,indent=2))
            print('UNCERTAIN LIMIT CHECK:',json.dumps(output,ensure_ascii=False),flush=True)
    print('Read-only checks finished. Case states and ledger unchanged; no limit decreases performed.',flush=True)


if __name__=='__main__':main()
