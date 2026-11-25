"""Compare independent enrollment counts without adding overlapping sources."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from collect_matryoshka_grafana import epoch, ROOT, PARTICIPANTS
from prepare_openvpn import private_write

def reconcile(db_path, snapshot):
    if snapshot.get('verified') is not True:
        raise ValueError('Unverified participant snapshot')
    source_time = epoch(snapshot['observed_at'])
    db = sqlite3.connect('file:' + str(db_path) + '?mode=ro', uri=True)
    try:
        meta = dict(db.execute('SELECT key,value FROM meta'))
        result = []
        seen = set()
        for p in snapshot['participants']:
            identity = str(p['courier_id'])
            if identity in seen:
                raise ValueError('Duplicate participant')
            seen.add(identity)
            count = p.get('delivered_orders')
            if p.get('count_scope') != 'delivered_since_enrollment' or type(count) is not int or count < 0:
                raise ValueError('Unverified historical count')
            start = epoch(p['enrolled_at'])
            # Comparable temporal boundary, not proof of identical source coverage.
            local_at_source = db.execute('SELECT count(*) FROM orders WHERE courier_id=? AND delivered>=? AND delivered<=?',
                                         (identity, start, source_time)).fetchone()[0]
            newer = db.execute('SELECT count(*) FROM orders WHERE courier_id=? AND delivered>=? AND delivered>?',
                               (identity, start, source_time)).fetchone()[0]
            result.append({'courier_id':identity,'name':p.get('name',identity),'enrollment_id':p['enrollment_id'],
                           'enrolled_at':p['enrolled_at'],'superset_total':count,
                           'grafana_known_at_superset_time':local_at_source,'grafana_known_newer':newer,
                           'difference':count-local_at_source,
                           'status':'counts_match_only' if count==local_at_source else 'needs_history_reconciliation',
                           'combined_total':None,'automatic_transition_allowed':False})
        return {'generated_at':datetime.now(timezone.utc).isoformat(),'superset_observed_at':snapshot['observed_at'],
                'grafana_last_success':meta.get('last_success'),'participants':result,
                'note':'Sources overlap. Snapshot observation time is not a source completeness watermark. Totals are not added.'}
    finally:
        db.close()

def save_report(snapshot):
    report = reconcile(ROOT/'orders.sqlite3',snapshot)
    private_write(ROOT/'reconciliation.json',json.dumps(report,ensure_ascii=False,indent=2))
    return report

if __name__=='__main__':
    os.umask(0o077)
    report=save_report(json.loads(PARTICIPANTS.read_text()))
    print(json.dumps(report,ensure_ascii=False,indent=2))
