"""Read-only before/after service timing and attendance backlog; no test writes/sends."""
import json
import time
import math
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
import sqlite3
import subprocess
from zoneinfo import ZoneInfo
TZ=ZoneInfo('Europe/Moscow')
ROOT=Path('/opt/courier-analytics/private')
UNITS=('courier-attendance-bot.service','courier-matryoshka.service','courier-matryoshka-pools.service','courier-medical.service')


def statistics(values):
    if not values:return {'count':0,'mean_seconds':None,'p50_seconds':None,'p95_seconds':None}
    ordered=sorted(values)
    return {'count':len(values),'mean_seconds':round(sum(values)/len(values),2),
            'p50_seconds':round(ordered[math.ceil(.5*len(ordered))-1],2),'p95_seconds':round(ordered[math.ceil(.95*len(ordered))-1],2)}


def phase(stamp,vpn,secondary):
    if secondary is not None and stamp>=secondary:return 'after_second_account'
    if vpn is not None and stamp>=vpn:return 'persistent_vpn_only'
    return 'before_persistent_vpn'


def analyze(records,vpn=None,secondary=None):
    groups=defaultdict(lambda:{'durations':[],'signals':Counter()})
    start=None;cycle_phase=None
    for stamp,message in sorted(records):
        label=phase(stamp,vpn,secondary);group=groups[label]
        signals={'vpn_wait':'Corporate VPN resource queued' in message or 'Corporate VPN queue wait expired' in message,
                 'onec_deferred':'1C read deferred:' in message,
                 'pool_deferred':'Pool collection deferred:' in message,
                 'managed_connection':'Using managed corporate VPN' in message,
                 'pool_verified':'"pool_read": true' in message,
                 'source_success':'Background evidence refresh finished; exit: 0' in message,
                 'read_failed':'1C worker did not complete:' in message,
                 'job_failure':'Failed with result' in message}
        group['signals'].update(key for key,value in signals.items() if value)
        if message.startswith('Starting '):start=stamp;cycle_phase=label
        elif message.startswith('Finished ') and start is not None:
            if cycle_phase==label:group['durations'].append(stamp-start)
            else:group['signals']['transition_cycle_excluded']+=1
            start=None
        elif 'Failed with result' in message:start=None
    return {key:{'completed_service_cycles':statistics(value['durations']),'log_signals':dict(value['signals'])} for key,value in groups.items()}


def journal(unit):
    result=subprocess.run(['journalctl','-u',unit,'--since','4 hours ago','-n','4000','-o','json','--no-pager'],capture_output=True,text=True,timeout=25)
    if result.returncode:return [],'journal_unavailable'
    records=[]
    for line in result.stdout.splitlines():
        row=json.loads(line);message=row.get('MESSAGE')
        if isinstance(message,str):records.append((int(row['__REALTIME_TIMESTAMP'])/1e6,message))
    return records,None


def boundaries():
    vpn=Path('/etc/courier-vpn/shared.json');secondary=Path('/etc/superset-telegram/onec-secondary.json')
    first=vpn.stat().st_mtime if vpn.exists() else None
    second=None
    if secondary.exists():second=datetime.fromisoformat(json.loads(secondary.read_text())['verified_at']).timestamp()
    return first,second


def backlog():
    path=ROOT/'attendance-bot/cases.sqlite3'
    if not path.exists():return {'available':False}
    today=datetime.now(TZ).date().isoformat();states=Counter();shops=defaultdict(Counter);pending_ages=[];reasons=Counter()
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        for row in db.execute('SELECT payload,state,message_id,observed,last_read_error FROM cases'):
            p=json.loads(row['payload'])
            if p.get('date')!=today:continue
            states[row['state']]+=1;shops[str(p['shop_id'])][row['state']]+=1
            if row['state']=='pending_review' and row['observed']:
                pending_ages.append(max(0,datetime.now(timezone.utc).timestamp()-row['observed']))
            if row['last_read_error']:reasons['cases_with_recorded_read_error']+=1
        meta=dict(db.execute("SELECT key,value FROM meta WHERE key IN ('last_loop','last_source_success')"))
    return {'date':today,'states':dict(states),'by_shop':{k:dict(v) for k,v in shops.items()},'pending_review_limit_age_seconds':statistics(pending_ages),'recorded_errors':dict(reasons),'heartbeat':meta,
            'detection_to_message_seconds':None,'latency_note':'First detection and successful send timestamps were not recorded. Limit age is not delivery latency.'}


def sample_locks(seconds=30):
    samples=Counter();errors=0
    for index in range(seconds):
        result=subprocess.run(['lslocks','--json','--output','PATH,MODE'],capture_output=True,text=True,timeout=5)
        if result.returncode:errors+=1
        else:
            locks=json.loads(result.stdout).get('locks',[])
            paths={row.get('path') for row in locks if row.get('mode')=='WRITE'}
            primary='/opt/courier-analytics/onec-roster.lock' in paths
            secondary='/opt/courier-analytics/onec-secondary.lock' in paths
            samples['both_account_locks_held' if primary and secondary else 'primary_only' if primary else 'secondary_only' if secondary else 'neither']+=1
        if index+1<seconds:time.sleep(1)
    return {'requested_samples':seconds,'samples':dict(samples),'unavailable_samples':errors,
            'note':'Simultaneous account locks show overlapping tasks, not proof of simultaneous successful 1C responses. No overlap during this short window does not prove serialization.'}


def main():
    vpn,secondary=boundaries()
    def local(value):return datetime.fromtimestamp(value,TZ).isoformat() if value is not None else None
    report={'observed_at':datetime.now(TZ).isoformat(),'vpn_mode_enabled_at':local(vpn),'secondary_account_enabled_at':local(secondary),'window':'last 4 hours, max 4000 journal lines per service','services':{}}
    for unit in UNITS:
        records,error=journal(unit)
        report['services'][unit]={'error':error,'phases':analyze(records,vpn,secondary)}
    report['attendance_today']=backlog()
    report['account_lock_observation']=sample_locks()
    report['note']='Read-only. Service duration includes waiting and the whole batch; it is not per-courier browser time. Service completion alone does not prove fresh reads. Signals count log lines, not unique cases. Few cycles do not establish a stable speedup.'
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
