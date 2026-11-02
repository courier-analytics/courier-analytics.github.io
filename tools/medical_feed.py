"""Validate and merge anonymous valid-LMK daily aggregates."""
from datetime import date, datetime
import math
from zoneinfo import ZoneInfo


def validate(payload):
    if not isinstance(payload, dict) or payload.get('schema_version') != 1 or not isinstance(payload.get('records'), list):
        raise ValueError('Invalid medical feed')
    records, seen = [], set()
    for row in payload['records']:
        if not isinstance(row, dict):
            raise ValueError('Invalid medical record')
        day = date.fromisoformat(row['date'])
        timestamp = datetime.fromisoformat(row['reported_at'])
        if timestamp.tzinfo is None or timestamp.astimezone(ZoneInfo('Europe/Moscow')).date() != day:
            raise ValueError('Medical observation date mismatch')
        if row['shop_id'] not in (5818, 7745) or isinstance(row['shop_id'], bool):
            raise ValueError('Invalid medical shop')
        if row['source'] != 'powerbi_lmk' or row['basis'] != 'present_and_not_expired_lmk':
            raise ValueError('Invalid medical provenance')
        n, d, value = row['numerator'], row['denominator'], row['value']
        if any(type(x) is not int or not 0 <= x <= 9007199254740991 for x in (n, d)) or not 0 <= n <= d or not d:
            raise ValueError('Invalid medical counts')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value - n / d * 100) > .0051:
            raise ValueError('Invalid medical percentage')
        key = (row['date'], row['shop_id'])
        if key in seen:
            raise ValueError('Duplicate medical record')
        seen.add(key)
        records.append({key: row[key] for key in ('date', 'shop_id', 'numerator', 'denominator', 'value', 'source', 'basis', 'reported_at')})
    return {'schema_version': 1, 'records': records}


def merge(previous, incoming):
    records = {}
    for feed in (previous, incoming):
        if feed is None:
            continue
        for row in validate(feed)['records']:
            key = (row['date'], row['shop_id'])
            if key not in records or datetime.fromisoformat(row['reported_at']) >= datetime.fromisoformat(records[key]['reported_at']):
                records[key] = row
    return {'schema_version': 1, 'records': [records[key] for key in sorted(records)]}
