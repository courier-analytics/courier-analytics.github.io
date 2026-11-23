"""Collect explicitly assigned Matryoshka participants. No eligibility inference."""
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from matryoshka_history import metric
from matryoshka_alerts import TYPE_INDEX
from services_pilot import chart_data
from prepare_openvpn import private_write

START = '2026-11-13T00:00:00'
SHOPS = (8889, 7745, 9107)
TARGET = Path('/opt/courier-analytics/private/matryoshka-monitor.json')


def query(columns, metrics, filters, end, where=''):
    return {'datasource': {'id': 3035, 'type': 'table'}, 'force': True,
            'result_format': 'json', 'result_type': 'full', 'queries': [{
                'columns': columns, 'metrics': metrics, 'filters': filters,
                'granularity': 'date_supply', 'time_range': START + ' : ' + end,
                'extras': {'where': where, 'having': ''}, 'row_limit': 1001,
                'is_timeseries': False, 'orderby': [], 'post_processing': []}]}


def fetch(opener, token, payload):
    code, answer = chart_data(opener, token, payload)
    blocks = answer.get('result') if isinstance(answer, dict) else None
    if code != 200 or not isinstance(blocks, list) or len(blocks) != 1:
        print('Matryoshka monitor query HTTP: ' + str(code), flush=True)
        raise ValueError('Monitor source unavailable')
    b = blocks[0]
    rows = b.get('data')
    if b.get('error') or b.get('status') not in ('success', None) or not isinstance(rows, list) or len(rows) >= 1001:
        private_write(TARGET.with_name('matryoshka-monitor-error.json'), json.dumps(answer, ensure_ascii=False, indent=2))
        raise ValueError('Monitor response failed or truncated')
    return rows


def start_condition(rows):
    clauses = []
    starts = {}
    for row in rows:
        identity = str(row['id_courier'])
        start = row['program_first_order']
        if not identity.isdigit() or not isinstance(start, str) or not re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d', start):
            raise ValueError('Invalid program start')
        parsed = datetime.strptime(start, '%Y-%m-%d %H:%M:%S')
        if parsed < datetime.fromisoformat(START) or identity in starts:
            raise ValueError('Invalid or duplicate enrollment')
        starts[identity] = start
        clauses.append("(id_courier = " + identity + " AND date_delivered >= toDateTime('" + start + "', 'Europe/Moscow'))")
    if not clauses:
        raise ValueError('Empty participant query')
    return '(' + ' OR '.join(clauses) + ')', starts


def collect(opener, token):
    now = datetime.now(ZoneInfo('Europe/Moscow'))
    end = now.strftime('%Y-%m-%dT%H:%M:%S')
    # Find explicit program assignments at pilot shops, then find the FIRST
    # program delivery company-wide, including transfers to another shop.
    success = "status_name = 'Успешно завершен' AND date_delivered IS NOT NULL"
    partner = "(courier_kontr IS NULL OR trimBoth(courier_kontr) IN ('','-','—','–'))"
    program = "id_courier_type IN ('24','25','26','27','28','29','30','31')"
    current = fetch(opener, token, query(['id_courier'], ['qty_orders_delivered'], [
        {'col': 'shopno', 'op': 'IN', 'val': list(SHOPS)}], end, success + ' AND ' + partner + ' AND ' + program))
    ids = sorted({int(r['id_courier']) for r in current if r.get('id_courier') is not None})
    participants = []
    if ids:
        selected = [{'col': 'id_courier', 'op': 'IN', 'val': ids}]
        starts = fetch(opener, token, query(['id_courier'], [metric(
            "formatDateTime(min(date_delivered), '%Y-%m-%d %H:%i:%S', 'Europe/Moscow')", 'program_first_order')],
            selected, end, success + ' AND ' + program))
        where, by_id = start_condition(starts)
        counts = fetch(opener, token, query(['id_courier'], ['qty_orders_delivered',
            metric('argMax(id_courier_type, tuple(date_delivered,id_order))', 'observed_type'),
            metric('argMax(courier, tuple(date_delivered,id_order))', 'courier_name'),
            metric('argMax(shopno, tuple(date_delivered,id_order))', 'last_shop'),
            metric("formatDateTime(max(date_delivered), '%Y-%m-%d %H:%i:%S', 'Europe/Moscow')", 'last_delivery')],
            selected, end, success + ' AND ' + where))
        overdue_by_id = {}
        try:
            overdue_rows = fetch(opener, token, query(['id_courier'], ['cnt_all_0_sla_offline'],
                selected, end, success + ' AND ' + where))
            for row in overdue_rows:
                cid = str(row['id_courier']); value = row['cnt_all_0_sla_offline']
                if cid not in by_id or cid in overdue_by_id or type(value) is not int or value < 0:
                    raise ValueError('Invalid overdue source count')
                overdue_by_id[cid] = value
            if set(overdue_by_id) != set(by_id):raise ValueError('Incomplete overdue counts')
        except (ValueError, KeyError, TypeError):
            overdue_by_id = {}
            print('Matryoshka overdue counts unavailable; not replaced with zero', flush=True)
        seen = set()
        for r in counts:
            identity = str(r['id_courier'])
            if identity not in by_id or identity in seen:
                raise ValueError('Unexpected courier count')
            seen.add(identity)
            code = int(r['observed_type']) if str(r.get('observed_type')).isdigit() else None
            if code not in TYPE_INDEX:
                continue  # most recent delivered order shows participant has left the program
            count = r['qty_orders_delivered']
            if type(count) is not int or count < 0:
                raise ValueError('Invalid delivered count')
            start = by_id[identity].replace(' ', 'T') + '+03:00'
            participants.append({'courier_id': identity, 'enrollment_id': 'matryoshka-' + start,
                'enrolled_at': start, 'name': r.get('courier_name') or identity,
                'current_type': code, 'current_type_verified': True,
                'type_basis': 'latest_successful_order_not_live_courier_card',
                'count_scope': 'delivered_since_enrollment', 'delivered_orders': count,
                'last_shop': r['last_shop'], 'last_delivery': r['last_delivery'],
                'overdue_orders': overdue_by_id.get(identity),
                'overdue_basis': 'cnt_all_0_sla_offline',
                'overdue_scope': 'delivered_since_enrollment',
                'overdue_verified': identity in overdue_by_id})
        if seen != set(by_id):
            raise ValueError('Incomplete program history')
    output = {'verified': True, 'observed_at': datetime.now(ZoneInfo('Europe/Moscow')).isoformat(),
              'program_start': START + '+03:00', 'participants': participants,
              'enrollment_basis': 'first_successful_matryoshka_delivery',
              'eligibility_basis': 'explicit_program_type_assignment_only'}
    private_write(TARGET, json.dumps(output, ensure_ascii=False, indent=2))
    print('Matryoshka monitor saved; participants=' + str(len(participants)), flush=True)
