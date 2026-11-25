"""Read-only attendance failure inventory. No Telegram requests or 1C operations."""
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
ROOT=Path('/opt/courier-analytics/private/attendance-bot')
SAFE_REASONS={'courier_id_not_found','courier_id_not_unique','courier_name_id_mismatch','courier_search_unstable','card_identity_not_verified','limit_read_failed'}

def inspect(root=ROOT):
    db=sqlite3.connect('file:'+str(root/'cases.sqlite3')+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:
        columns={r[1] for r in db.execute('PRAGMA table_info(cases)')}
        if not {'last_read_error','read_attempts'}<=columns:raise ValueError('Database schema missing diagnostic fields')
        states=Counter();reasons=Counter();cases=[]
        for row in db.execute('SELECT payload,state,read_attempts,last_read_error,result FROM cases WHERE read_attempts>0 OR last_read_error IS NOT NULL'):
            payload=json.loads(row['payload'])
            if row['state'] in ('applied','skipped','withdrawn'):continue
            reason=row['last_read_error']
            safe=reason if reason in SAFE_REASONS else ('other_recorded_reason' if reason else 'no_detailed_reason')
            states[row['state']]+=1;reasons[safe]+=1
            cases.append({'date':payload.get('date'),'shop':payload.get('shop_id'),'courier_id':payload.get('courier_id'),
                          'state':row['state'],'attempts':row['read_attempts'],'reason':safe})
    finally:db.close()
    stages=Counter();categories=Counter();signals=Counter()
    path=root/'worker.log'
    if path.exists():
        with path.open('rb') as stream:
            size=path.stat().st_size
            stream.seek(max(0,size-4000000))
            data=stream.read().decode('utf-8',errors='replace')
        for value in re.findall(r'"stage_failed"\s*:\s*"([a-z_]{1,60})"',data):stages[value]+=1
        for value in re.findall(r'"error_category"\s*:\s*"([A-Za-z_]{1,60})"',data):categories[value]+=1
        for label,pattern in {'timeouts':r'"stage_timeout"\s*:\s*true','validation_failures':r'"stage_validation_failed"\s*:\s*true',
                              'vpn_busy':r'Corporate VPN.*(?:queued|busy|wait expired)','verified_reads':r'Attendance task result:.*"read"\s*:\s*true'}.items():
            signals[label]=len(re.findall(pattern,data))
    return {'unresolved_states':dict(states),'recorded_reasons':dict(reasons),'cases':cases,
            'worker_tail_stages':dict(stages),'worker_tail_error_categories':dict(categories),'worker_tail_signals':dict(signals),
            'note':'Worker statistics cover last 4 MB, not a fixed date range. Repeated attempts may refer to the same case.'}

if __name__=='__main__':print(json.dumps(inspect(),ensure_ascii=False,indent=2))
