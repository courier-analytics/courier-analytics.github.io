"""Read slot APIs, save a private XLSX, and refresh the public dashboard feed."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from build_dashboard_feed import build
from enrich_slots import atomic_json, enrich, fetch, report
from import_slots import parse_rows

HEADERS = ['Дата', 'Код ТТ', 'ID кластера', 'ID слота', 'Тип слота',
           'Начало', 'Окончание', 'Записалось', 'ID курьера',
           'Статус смены', 'Начало смены', 'Окончание смены']


def rows_from_api(day, shop, scope_kind, identity, payload):
    items = payload if isinstance(payload, list) else payload.get('slots', payload.get('items'))
    if not isinstance(items, list):
        raise ValueError('Unknown slot response')
    rows = []
    for item in items:
        kind = str(item.get('type', item.get('slot_type', item.get('slotType', '')))).lower()
        if kind != 'limited':
            raise ValueError('Limited-only response contains another type')
        actual_id = item.get('shopno_cluster_id', item.get('shopno', item.get('shop_id')))
        if actual_id is None or int(actual_id) != identity:
            raise ValueError('Unexpected API scope')
        if item.get('date') and str(item['date'])[:10] != day:
            raise ValueError('Unexpected API date')
        if scope_kind == 'shopno' and item.get('is_cluster') is True:
            raise ValueError('Cluster returned for direct shop')
        capacity = item.get('capacity', item.get('courier_limits'))
        if type(capacity) is not int or capacity < 0:
            raise ValueError('Invalid capacity')
        people = item.get('couriers')
        if not isinstance(people, list):
            raise ValueError('Courier list missing')
        people = [p for p in people if p.get('status') != 'cancelled']
        occupied = item.get('occupied', item.get('booked', item.get('total_occupied')))
        if type(occupied) is not int or occupied != len(people):
            raise ValueError('API occupancy differs from courier details')
        ids = [str(p['id']) for p in people]
        if len(set(ids)) != len(ids) or any(not p.isdigit() for p in ids):
            raise ValueError('Repeated or invalid courier ID')
        slot_id = item.get('slot_id', item.get('limited_slot_id'))
        if type(slot_id) is not int or slot_id <= 0:
            raise ValueError('Invalid slot ID')
        one = people[0] if len(people) == 1 else {}
        rows.append([day, str(shop), str(identity) if scope_kind == 'cluster_id' else '',
                     slot_id, 'Лимитированный', str(item['time_from'])[:5],
                     str(item['time_to'])[:5], f'{len(people)} из {capacity}', ', '.join(ids),
                     one.get('shift_status') or '', one.get('shift_start') or '',
                     one.get('shift_end') or ''])
    return rows


def merge_feed(previous, incoming):
    # Revalidate the old public feed and copy only allowlisted fields.
    reports = []
    if previous:
        if previous.get('schema_version') != 1:
            raise ValueError('Invalid previous feed')
        incoming_keys = {(r['date'], r['shop_id']) for r in incoming['records']}
        for row in previous['records']:
            if (row['date'], row['shop_id']) in incoming_keys:
                continue
            reports.append({'schema_version': 1, 'snapshot_consistent': True, 'issues': [],
                'generated_at': row['reported_at'], 'summaries': [{
                    **{k: row[k] for k in ('date', 'shop_id', 'booked_places', 'capacity', 'fill_percent')},
                    'slot_type': 'limited'}]})
    for row in incoming['records']:
        reports.append({'schema_version': 1, 'snapshot_consistent': True, 'issues': [],
            'generated_at': row['reported_at'], 'summaries': [{
                **{k: row[k] for k in ('date', 'shop_id', 'booked_places', 'capacity', 'fill_percent')},
                'slot_type': 'limited'}]})
    return build(reports)


def private_xlsx(path, rows):
    from openpyxl import Workbook
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.export-', suffix='.xlsx', dir=path.parent)
    os.close(fd)
    try:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Смены'
        sheet.append(HEADERS)
        for row in rows:
            sheet.append(row)
        workbook.save(temporary)
        workbook.close()
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def refresh(config, day, token, proxy, private_dir, feed_path):
    responses, rows = [], []
    if config.get('schema_version') != 1 or not config.get('shops'):
        raise ValueError('Scope configuration missing')
    seen = set()
    for shop in config['shops']:
        identity = shop['shop_id']
        if identity not in (5818, 7745) or identity in seen:
            raise ValueError('Unknown or repeated shop')
        seen.add(identity)
        if shop.get('scope_verified') is not True:
            raise ValueError('Shop scope must be verified before collection')
        scope_list = [('shopno', identity)] + [('cluster_id', int(c)) for c in shop['cluster_ids']]
        if len(set(scope_list)) != len(scope_list):
            raise ValueError('Duplicate scope')
        for kind, value in scope_list:
            scope = (day, kind, value, 'limited')
            payload = fetch(scope, token, proxy)
            responses.append((*scope, payload))
            rows.extend(rows_from_api(day, identity, kind, value, payload))
    if not rows:
        raise ValueError('Empty API response; previous report preserved')
    slots = parse_rows(HEADERS, rows)
    enriched, issues = enrich(slots, responses)
    if issues:
        raise ValueError('Inconsistent API snapshot; previous report preserved')
    details = report(enriched, issues)
    fresh = build([details])
    previous = json.loads(feed_path.read_text()) if feed_path.exists() else None
    feed = merge_feed(previous, fresh)
    private_xlsx(private_dir / ('slots-' + day + '.xlsx'), rows)
    atomic_json(private_dir / ('summary-' + day + '.json'), details)
    atomic_json(feed_path, feed)
    feed_path.chmod(0o644)
    return details


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scopes', type=Path, required=True)
    parser.add_argument('--session', type=Path, default=Path('/root/curator-session.json'))
    parser.add_argument('--proxy', default=os.environ.get('COURIER_PROXY_URL', 'socks5h://127.0.0.1:18080'))
    parser.add_argument('--private-dir', type=Path, default=Path('/opt/courier-analytics/private'))
    parser.add_argument('--feed', type=Path, required=True)
    parser.add_argument('--date', default=datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat())
    args = parser.parse_args()
    from datetime import date
    date.fromisoformat(args.date)
    try:
        token = json.loads(args.session.read_text()).get('token')
        if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
            raise ValueError('Invalid session')
        args.private_dir.mkdir(parents=True, exist_ok=True)
        args.private_dir.chmod(0o700)
        result = refresh(json.loads(args.scopes.read_text()), args.date, token,
                         args.proxy, args.private_dir, args.feed)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except RuntimeError as error:
        raise SystemExit(str(error))
    except (ValueError, KeyError, OSError, TypeError):
        raise SystemExit('Refresh failed validation; public feed preserved.')
