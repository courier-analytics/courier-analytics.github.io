"""Import exact Superset order history; preserve Grafana evidence and deduplicate by order ID."""
import fcntl
import json
import os
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from collect_matryoshka_grafana import ROOT, PARTICIPANTS, epoch
from prepare_openvpn import private_write

def merge(db_path, comparison, snapshot):
    if snapshot.get('verified') is not True:raise ValueError('Unverified participants')
    participants={str(p['courier_id']):p for p in snapshot['participants']}
    prepared={}
    for person in comparison['participants']:
        cid=str(person['courier_id'])
        if cid not in participants:raise ValueError('Participant selection changed')
        for row in person['superset_rows']:
            if str(row['id_courier'])!=cid or row.get('id_order') is None:raise ValueError('Invalid order identity')
            identity=str(row['id_order'])
            stamp=row['delivered_at']
            moment=epoch(stamp)
            value=(cid,moment,stamp)
            if identity in prepared and prepared[identity]!=value:raise ValueError('Conflicting source order')
            prepared[identity]=value
    db=sqlite3.connect(db_path)
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS superset_orders(order_id TEXT PRIMARY KEY,courier_id TEXT NOT NULL,delivered REAL NOT NULL,raw_time TEXT NOT NULL)')
            for identity,(cid,moment,raw) in prepared.items():
                local=db.execute('SELECT courier_id FROM orders WHERE order_id=?',(identity,)).fetchone()
                if local and local[0]!=cid:raise ValueError('Order courier mismatch')
                old=db.execute('SELECT courier_id FROM superset_orders WHERE order_id=?',(identity,)).fetchone()
                if old and old[0]!=cid:raise ValueError('Historical courier mismatch')
                db.execute('INSERT INTO superset_orders VALUES(?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET delivered=excluded.delivered,raw_time=excluded.raw_time',(identity,cid,moment,raw))
            result=[]
            for cid,p in participants.items():
                start=epoch(p['enrolled_at'])
                # Superset time is used only for the exact order ID that supplied it.
                confirmed=db.execute('SELECT count(*) FROM superset_orders WHERE courier_id=? AND delivered>=?',(cid,start)).fetchone()[0]
                both=db.execute('SELECT count(*) FROM superset_orders s JOIN orders g USING(order_id) WHERE s.courier_id=? AND s.delivered>=?',(cid,start)).fetchone()[0]
                only_grafana=db.execute('SELECT count(*) FROM orders g LEFT JOIN superset_orders s USING(order_id) WHERE g.courier_id=? AND s.order_id IS NULL',(cid,)).fetchone()[0]
                diagnostic=db.execute('SELECT count(*) FROM orders g LEFT JOIN superset_orders s USING(order_id) WHERE g.courier_id=? AND s.order_id IS NULL AND g.delivered+10800>=?',(cid,start)).fetchone()[0]
                result.append({'courier_id':cid,'name':p.get('name'), 'confirmed_superset_unique_orders':confirmed,'also_in_grafana':both,
                               'grafana_only_orders_pending_time_verification':only_grafana,
                               'grafana_only_after_enrollment_if_plus_3h':diagnostic,
                               'automatic_transition_allowed':False})
        return {'generated_at':datetime.now(timezone.utc).isoformat(),'participants':result,
                'time_basis':'Exact-ID Superset evidence; original Grafana timestamps unchanged. +3h is diagnostic only.'}
    finally:db.close()

def main():
    os.umask(0o077)
    with (ROOT/'collector.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        snapshot=json.loads(PARTICIPANTS.read_text())
        comparison=json.loads((ROOT/'order-id-comparison.json').read_text())
        backup=ROOT/('orders-before-history-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.sqlite3')
        with sqlite3.connect(ROOT/'orders.sqlite3') as source, sqlite3.connect(backup) as target:source.backup(target)
        report=merge(ROOT/'orders.sqlite3',comparison,snapshot)
        private_write(ROOT/'unified-history.json',json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
