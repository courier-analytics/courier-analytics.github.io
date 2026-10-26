"""Read the site's grouped XLSX export; print aggregates, never courier identities."""
import argparse
from collections import defaultdict
from datetime import date
import json
from pathlib import Path
import re


def parse_rows(headers, rows):
    required = {'Дата', 'Код ТТ', 'ID кластера', 'ID слота', 'Тип слота',
                'Начало', 'Окончание', 'Записалось', 'ID курьера',
                'Статус смены', 'Начало смены', 'Окончание смены'}
    if not required.issubset(headers):
        raise ValueError('Missing export columns: ' + ', '.join(sorted(required - set(headers))))
    result, seen = [], set()
    for values in rows:
        if not any(v not in (None, '') for v in values):
            continue
        row = dict(zip(headers, values))
        def text(key):
            return str(row.get(key) if row.get(key) is not None else '').strip()
        day = date.fromisoformat(text('Дата')).isoformat()
        kind = {'Лимитированный': 'limited', 'Ручной': 'manual'}.get(text('Тип слота'))
        if kind is None:
            raise ValueError('Unknown slot type')
        slot_id = int(text('ID слота'))
        key = (day, kind, slot_id)
        if key in seen:
            raise ValueError('Duplicate slot in export')
        seen.add(key)
        counts = re.fullmatch(r'(\d+)\s+из\s+(\d+)', text('Записалось'))
        if not counts:
            raise ValueError('Unknown occupancy format')
        booked, capacity = map(int, counts.groups())
        raw_ids = text('ID курьера')
        ids = [part.strip() for part in raw_ids.split(',')] if raw_ids else []
        if any(not value.isdigit() for value in ids) or len(set(ids)) != len(ids):
            raise ValueError('Invalid or repeated courier ID')
        if len(ids) != booked:
            raise ValueError('Occupancy and courier count disagree')
        # Grouped XLSX rows do not contain individual shift facts.
        individual = len(ids) == 1
        couriers = [{
            'courier_id': identity,
            'shift_status': (text('Статус смены') or None) if individual else None,
            'shift_start': (text('Начало смены') or None) if individual else None,
            'shift_end': (text('Окончание смены') or None) if individual else None,
            'details_source': 'xlsx_single_courier' if individual else 'api_required',
        } for identity in ids]
        result.append({
            'date': day, 'shop_id': int(text('Код ТТ')),
            'cluster_id': int(text('ID кластера')) if text('ID кластера') else None,
            'slot_id': slot_id, 'slot_type': kind,
            'time_from': text('Начало'), 'time_to': text('Окончание'),
            'booked': booked, 'capacity': capacity, 'couriers': couriers,
        })
    return result


def summarize(slots):
    groups = defaultdict(list)
    for slot in slots:
        groups[(slot['date'], slot['shop_id'], slot['slot_type'])].append(slot)
    summaries = []
    for (day, shop, kind), rows in sorted(groups.items()):
        booked = sum(r['booked'] for r in rows)
        capacity = sum(r['capacity'] for r in rows)
        summaries.append({
            'date': day, 'shop_id': shop, 'slot_type': kind,
            'slots': len(rows), 'booked_places': booked, 'capacity': capacity,
            'fill_percent': round(100 * booked / capacity, 2) if capacity else None,
            'cluster_ids': sorted({r['cluster_id'] for r in rows if r['cluster_id'] is not None}),
            'direct_shop_slots': sum(r['cluster_id'] is None for r in rows),
            'group_slots': sum(len(r['couriers']) > 1 for r in rows),
            'empty_slots': sum(not r['couriers'] for r in rows),
            'courier_slot_records': sum(len(r['couriers']) for r in rows),
            'unique_couriers': len({c['courier_id'] for r in rows for c in r['couriers']}),
            'records_requiring_api': sum(c['details_source'] == 'api_required'
                                         for r in rows for c in r['couriers']),
            'records_missing_shift_end': sum(c['shift_end'] is None
                                            for r in rows for c in r['couriers']),
        })
    return summaries


def read_export(path):
    from openpyxl import load_workbook
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook['Смены']
        iterator = sheet.values
        return parse_rows(next(iterator), iterator)
    finally:
        workbook.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('xlsx', type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(read_export(args.xlsx)), ensure_ascii=False, indent=2))
