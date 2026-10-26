"""Publish an allowlist of anonymous slot-fill aggregates, never raw imports."""
import argparse
from datetime import date, datetime
import json
import math
from pathlib import Path

from enrich_slots import atomic_json

METRIC_KEYS = {'slot_fill', 'shift_marked', 'planned_attendance', 'planned_late',
               'unplanned_work', 'planned_completion'}
REASONS = {'zero_denominator', 'assigned_roster_not_verified', 'active_base_incomplete',
           'bookings_outside_verified_roster', 'frozen_plan_missing',
           'planned_booking_missing_from_current_data', 'planned_slot_times_changed',
           'unknown_planned_shift_status', 'unknown_shift_status',
           'shift_end_or_final_status_missing'}
BASES = {'limited_slot_places', 'all_assigned_unique_couriers', 'direct_shop_scheduled_unique_5d_including_day',
         'current_limited_bookings_unique_couriers',
         'current_limited_all_shifts_site_10min_tolerance',
         'frozen_plan_unique_couriers', 'manual_work_without_frozen_plan',
         'frozen_plan_all_shifts_site_10min_tolerance'}


def validate_metrics(metrics):
    if not isinstance(metrics, dict) or not set(metrics).issubset(METRIC_KEYS):
        raise ValueError('Unknown metrics')
    clean = {}
    for key, item in metrics.items():
        n, d, value = item.get('numerator'), item.get('denominator'), item.get('value')
        reason, basis = item.get('reason'), item.get('basis')
        if reason is not None and reason not in REASONS:
            raise ValueError('Unknown metric reason')
        if basis is not None and basis not in BASES:
            raise ValueError('Unknown metric basis')
        if any(v is not None and (type(v) is not int or v < 0) for v in (n, d)):
            raise ValueError('Invalid metric counts')
        if value is not None:
            if reason is not None or n is None or not d or type(value) not in (float, int) or not math.isfinite(value):
                raise ValueError('Unverified or invalid percentage')
            if abs(value-round(n/d*100, 2)) > .011:
                raise ValueError('Metric percentage does not match counts')
            if key != 'slot_fill' and n > d:
                raise ValueError('Unique-courier numerator exceeds denominator')
        elif reason is None:
            raise ValueError('Missing metric requires an explicit reason')
        clean[key] = {'value': value, 'numerator': n, 'denominator': d,
                      'reason': reason, 'basis': basis}
    return clean


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
            if type(shop) is not int or shop not in (5818, 7745, 4747):
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
            if 'metrics' in row:
                record['metrics'] = validate_metrics(row['metrics'])
                fill = record['metrics'].get('slot_fill')
                if fill and (fill['numerator'] != booked or fill['denominator'] != capacity or fill['value'] != percent):
                    raise ValueError('Slot metric differs from slot totals')
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
