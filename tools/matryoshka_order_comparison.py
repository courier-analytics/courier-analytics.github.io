"""Read-only comparison of native order identifiers; does not assume namespaces match."""
import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from matryoshka_monitor_source import query, fetch, start_condition, TARGET
from matryoshka_history import metric
from prepare_openvpn import private_write
from collect_matryoshka_grafana import ROOT, epoch

def compare_ids(source_rows, local_ids):
    source={str(r['id_order']) for r in source_rows}
    local=set(local_ids)
    return {'superset_unique_ids':len(source),'grafana_unique_ids':len(local),'matching_ids':len(source & local),
            'only_superset':sorted(source-local),'only_grafana':sorted(local-source),
            'identity_namespace_verified':False}

def collect(opener,token):
    snapshot=json.loads(TARGET.read_text())
    if snapshot.get('verified') is not True:raise ValueError('Unverified participants')
    db=sqlite3.connect('file:'+str(ROOT/'orders.sqlite3')+'?mode=ro',uri=True)
    reports=[]
    try:
        for participant in snapshot['participants']:
            identity=str(participant['courier_id'])
            start=datetime.fromisoformat(participant['enrolled_at']).astimezone(ZoneInfo('Europe/Moscow')).strftime('%Y-%m-%d %H:%M:%S')
            where,_=start_condition([{'id_courier':identity,'program_first_order':start}])
            end=datetime.now(ZoneInfo('Europe/Moscow')).strftime('%Y-%m-%dT%H:%M:%S')
            payload=query(['id_courier','id_order'],['qty_orders_delivered',metric("formatDateTime(max(date_delivered), '%Y-%m-%d %H:%i:%S', 'Europe/Moscow')",'delivered_at')],
                          [{'col':'id_courier','op':'IN','val':[int(identity)]}],end,"status_name = 'Успешно завершен' AND date_delivered IS NOT NULL AND "+where)
            rows=fetch(opener,token,payload)
            if any(str(r['id_courier'])!=identity or r.get('id_order') is None for r in rows):raise ValueError('Unexpected order identity')
            local=[r[0] for r in db.execute('SELECT order_id FROM orders WHERE courier_id=? AND delivered>=?',(identity,epoch(participant['enrolled_at'])))]
            report=compare_ids(rows,local)
            report.update(courier_id=identity,name=participant.get('name'),superset_rows=rows)
            reports.append(report)
            print('Order comparison:',json.dumps({k:v for k,v in report.items() if k not in ('only_superset','only_grafana','superset_rows')},ensure_ascii=False),flush=True)
    finally:db.close()
    private_write(ROOT/'order-id-comparison.json',json.dumps({'participants':reports,'note':'Native id_order and parcel_id may use different namespaces; no ledger changes.'},ensure_ascii=False,indent=2))
