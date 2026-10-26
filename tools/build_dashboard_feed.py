"""Publish an allowlist of anonymous slot-fill aggregates, never raw imports."""
import argparse
from datetime import date, datetime
import json
import math
from pathlib import Path

from enrich_slots import atomic_json


def build(reports):
    records = {}
    for report in reports:
        if report.get('schema_version') != 1 or report.get('snapshot_consistent') is not True or report.get('issues'):
            raise ValueError('Inconsistent import cannot be published')
        generated = report['generated_at']
        if datetime.fromisoformat(generated.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('Report timestamp must have timezone')
        for row in report['summaries']:
            if row['slot_type'] != 'limited':
                continue
            day = date.fromisoformat(row['date']).isoformat()
            shop = row['shop_id']
            if type(shop) is not int or shop not in (5818, 7745):
                raise ValueError('Unknown dashboard shop')
            booked, capacity = row['booked_places'], row['capacity']
            if any(type(v) is not int or v < 0 for v in (booked, capacity)):
                raise ValueError('Invalid counts')
            if capacity == 0 and booked:
                raise ValueError('Occupied places without capacity')
            percent = round(booked / capacity * 100, 2) if capacity else None
            claimed = row['fill_percent']
            if percent is None:
                if claimed is not None:
                    raise ValueError('Zero capacity cannot have a percentage')
            elif type(claimed) not in (int, float) or not math.isfinite(claimed) or abs(claimed-percent) > .011:
                raise ValueError('Percentage does not match counts')
            record = {'date': day, 'shop_id': shop, 'booked_places': booked,
                      'capacity': capacity, 'fill_percent': percent,
                      'source': 'slots_export', 'reported_at': generated}
            key = (day, shop)
            if key in records:
                raise ValueError('Duplicate day and shop; choose one explicit snapshot')
            records[key] = record
    if not records:
        raise ValueError('No limited-slot observations')
    return {'schema_version': 1, 'records': [records[k] for k in sorted(records)]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reports', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        output = build([json.loads(p.read_text()) for p in args.reports])
        atomic_json(args.output, output)
        # Public aggregates contain no identities. They must be readable by the web server.
        args.output.chmod(0o644)
        print('Dashboard feed saved:', args.output)
    except (ValueError, KeyError, TypeError):
        raise SystemExit('Invalid report; existing dashboard feed preserved')
