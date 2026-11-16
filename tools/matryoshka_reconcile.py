"""Read-only count comparison; no Telegram calls or delivery journal changes."""
import json
from pathlib import Path
from matryoshka_monitor_source import collect, query, fetch, TARGET
from matryoshka_history import metric
from prepare_openvpn import private_write


def reconcile(opener, token):
    collect(opener, token)
    snapshot = json.loads(TARGET.read_text())
    ids = [int(p['courier_id']) for p in snapshot['participants']]
    if not ids:
        print('No active Matryoshka participants to reconcile', flush=True)
        return
    end = snapshot['observed_at'][:19]
    rows = fetch(opener, token, query(['id_courier', 'id_courier_type',
        {'expressionType':'SQL','sqlExpression':"formatDateTime(date_delivered, '%Y-%m-%d', 'Europe/Moscow')",'label':'delivery_day'},
        {'expressionType':'SQL','sqlExpression':"formatDateTime(date_supply, '%Y-%m-%d', 'Europe/Moscow')",'label':'supply_day'}],
        ['qty_orders_delivered',
         metric("formatDateTime(min(date_delivered), '%Y-%m-%d %H:%i:%S', 'Europe/Moscow')", 'first_delivery'),
         metric("formatDateTime(max(date_delivered), '%Y-%m-%d %H:%i:%S', 'Europe/Moscow')", 'last_delivery'),
         metric('any(toTypeName(date_delivered))','source_time_type')],
        [{'col':'id_courier','op':'IN','val':ids}], end,
        "status_name = 'Успешно завершен' AND date_delivered IS NOT NULL"))
    result = {'snapshot': snapshot, 'daily_by_type': rows,
              'note': 'Same native successful general-order metric, without enrollment-time cutoff. Date/type subtotals may overlap general orders; do not sum them as an authoritative total.'}
    private_write(TARGET.with_name('matryoshka-reconciliation.json'), json.dumps(result, ensure_ascii=False, indent=2))
    for p in snapshot['participants']:
        print('Courier ID '+p['courier_id']+'; bot count='+str(p['delivered_orders'])+'; first program delivery='+p['enrolled_at'],flush=True)
    for r in rows:
        print('Count audit: '+json.dumps(r,ensure_ascii=False),flush=True)
