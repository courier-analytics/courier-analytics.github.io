"""Read-only history discovery. Does not establish eligibility or send alerts."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from services_pilot import chart_data
from prepare_openvpn import private_write


def metric(sql, label):
    return {'expressionType': 'SQL', 'sqlExpression': sql, 'label': label, 'hasCustomLabel': True}


def history_payload(rows, observed_at=None):
    now = datetime.fromisoformat(observed_at) if observed_at else datetime.now(ZoneInfo("Europe/Moscow"))
    if now.tzinfo is None:
        raise ValueError("History timestamp must have timezone")
    now = now.astimezone(ZoneInfo("Europe/Moscow"))
    try:
        start = now.replace(year=now.year - 2) - timedelta(days=7)
    except ValueError:  # February 29
        start = now.replace(year=now.year - 2, day=28) - timedelta(days=7)
    time_range = start.strftime("%Y-%m-%dT%H:%M:%S") + " : " + now.strftime("%Y-%m-%dT%H:%M:%S")
    from matryoshka_source import employment
    ids = sorted({int(r['id_courier']) for r in rows
                  if employment(r) == 'self_employed' and r.get('id_courier') is not None})
    if not ids or len(ids) > 1000:
        raise ValueError('Missing or excessive candidate IDs')
    def query(columns, metrics, filters, limit):
        return {'columns': columns, 'metrics': metrics, 'filters': filters,
                'row_limit': limit, 'is_timeseries': False, 'orderby': [],
                'granularity': 'date_supply', 'time_range': time_range,
                'extras': {'where': '', 'having': ''}, 'post_processing': []}
    bounds = [metric('min(date_delivered)', 'first_available_delivery'),
              metric('max(date_delivered)', 'last_available_delivery')]
    # No shop, partner or courier-type filter: transfers and type changes must
    # not reset history. All counts remain diagnostic until coverage is verified.
    filters = [{'col': 'id_courier', 'op': 'IN', 'val': ids}]
    queries = [query(['id_courier'], ['qty_orders_delivered'] + bounds + [
        metric("countIf(id_courier_type IN ('24','25','26','27','28','29','30','31'))", 'matryoshka_source_rows')], filters, 1001),
        query([], bounds, filters, 1)]
    # Small deterministic sample for inspecting activity gaps without exporting
    # the entire company's order-level or personal data.
    samples = ids[:3]
    queries.append(query(['id_courier', {'expressionType': 'SQL',
        'sqlExpression': 'toDate(date_delivered)', 'label': 'delivery_day'}],
        ['qty_orders_delivered'], [{'col': 'id_courier', 'op': 'IN', 'val': samples},
        {'col': 'date_delivered', 'op': 'IS NOT NULL', 'val': None}], 6000))
    return {'datasource': {'id': 3035, 'type': 'table'}, 'force': False,
            'result_format': 'json', 'result_type': 'full', 'queries': queries}


def response_diagnostic(code, answer):
    text = json.dumps(answer, ensure_ascii=False).lower()
    return {'phase': 'history_query', 'http_status': code,
            'result_blocks': len(answer['result']) if isinstance(answer, dict) and isinstance(answer.get('result'), list) else None,
            'timeout_reported': any(t in text for t in ('timeout', 'timed out', 'time limit')),
            'date_parse_reported': any(t in text for t in ('parse datetime', 'parse date', 'invalid date', 'invalid time', 'time range')),
            'memory_limit_reported': 'memory limit' in text,
            'sql_error_reported': any(t in text for t in ('syntax error', 'unknown identifier', 'unknown function')),
            'pending': code == 202,
            'history_updated': False}


def collect(opener, token, discovery, source):
    payload = history_payload(discovery['rows'], discovery.get('observed_at'))
    try:
        code, answer = chart_data(opener, token, payload)
    except (OSError, ValueError, TimeoutError) as error:
        diagnostic = {'phase': 'history_request', 'exception_type': type(error).__name__,
                      'history_updated': False}
        print('Matryoshka history diagnostic: ' + json.dumps(diagnostic), flush=True)
        private_write(Path('/opt/courier-analytics/private/matryoshka-history-error.json'),
                      json.dumps(diagnostic, indent=2))
        raise ValueError('History request failed; previous history file is stale') from None
    diagnostic = response_diagnostic(code, answer)
    print('Matryoshka history diagnostic: ' + json.dumps(diagnostic), flush=True)
    blocks = answer.get('result') if isinstance(answer, dict) else None
    if (code != 200 or not isinstance(blocks, list) or len(blocks) != len(payload['queries'])
            or any(not isinstance(b, dict) or b.get('error') or b.get('status') not in ('success', None) for b in blocks)):
        # Keep server error details private; never copy them into public logs.
        private_write(Path('/opt/courier-analytics/private/matryoshka-history-error.json'),
                      json.dumps({'diagnostic': diagnostic, 'response': answer,
                                  'requested_time_range': payload['queries'][0]['time_range']},
                                 ensure_ascii=False, indent=2))
        raise ValueError('History query incomplete; previous history file is stale')
    results = []
    for query, block in zip(payload['queries'], blocks):
        rows = block.get('data')
        if block.get('error') or block.get('status') not in ('success', None) or not isinstance(rows, list):
            raise ValueError('History query failed')
        if len(rows) >= query['row_limit'] and query['columns']:
            raise ValueError('History may be truncated')
        results.append(rows)
    output = {'observed_at': discovery['observed_at'], 'source_dataset': 3035,
              'eligibility_verified': False, 'history_scope': 'all_shops_all_partner_and_courier_types',
              'courier_summaries': results[0], 'candidate_bounds': results[1], 'requested_time_range': payload['queries'][0]['time_range'],
              'daily_samples': results[2],
              'source_definition': {key: source.get(key) for key in ('sql', 'main_dttm_col', 'filter_select_enabled')},
              'note': 'Available history is not proof of complete company history. Delivery dates do not establish connection date or current courier type. No alerts sent.'}
    target = Path('/opt/courier-analytics/private/matryoshka-history.json')
    private_write(target, json.dumps(output, ensure_ascii=False, indent=2))
    print('Matryoshka history saved privately; courier summaries=' + str(len(results[0])) + '. No messages sent.', flush=True)
