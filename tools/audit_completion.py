"""Explain incomplete completion facts from private snapshots; no names or phones."""
import argparse
from collections import Counter
from datetime import datetime, timedelta
import json
from pathlib import Path

from calculate_metrics import MOSCOW, period, timestamp
from enrich_slots import source_status
from dashboard_shops import TARGETS


def blockers(slots, now=None):
    now = now or datetime.now(MOSCOW)
    output = []
    for slot in slots:
        if slot['slot_type'] != 'limited':
            continue
        for person in slot['couriers']:
            state = source_status(person.get('shift_status'))
            reason = None
            try:
                start, end = period(slot)
            except (ValueError, KeyError, TypeError, AttributeError):
                reason = 'slot_time_missing_or_invalid'
            else:
                if end > now:
                    reason = 'slot_not_finished_yet'
                elif state == 'unknown':
                    reason = 'shift_status_unknown'
                elif state == 'no_show':
                    continue
                elif state == 'expected':
                    reason = 'shift_status_still_expected'
                elif not person.get('shift_end'):
                    reason = 'shift_end_missing'
                else:
                    actual = timestamp(person['shift_end'])
                    if actual is None:
                        try:
                            parsed = datetime.fromisoformat(person['shift_end'].replace('Z', '+00:00'))
                            reason = 'shift_end_timezone_missing' if parsed.tzinfo is None else 'shift_end_invalid'
                        except (ValueError, TypeError, AttributeError):
                            reason = 'shift_end_invalid'
                    elif actual > now:
                        reason = 'shift_end_in_future'
                    elif actual < start-timedelta(days=1):
                        reason = 'shift_end_date_inconsistent'
            if reason:
                output.append({'slot_id': slot['slot_id'], 'scope_kind': slot['scope_kind'],
                               'scope_id': slot['scope_id'], 'courier_id': person['courier_id'],
                               'status': state, 'reason': reason})
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--shop', type=int, choices=TARGETS, required=True)
    args = parser.parse_args()
    try:
        from datetime import date
        day = date.fromisoformat(args.date).isoformat()
        root = Path('/opt/courier-analytics/private')
        paths = [root/'backfill'/day/'all-shops/all-shops-observations.json',
                 root/'active-base-audit'/day/'all-shops-observations.json',
                 root/'all-shops/all-shops-observations.json']
        candidates = []
        for path in paths:
            if path.exists():
                data = json.loads(path.read_text())
                if data.get('date') == day:
                    candidates.append((data, path))
        if not candidates:
            raise ValueError('No dated snapshot')
        data, path = max(candidates, key=lambda pair: pair[0]['generated_at'])
        shop = next(s for s in data['shops'] if s['shop_id'] == args.shop)
        issues = blockers(shop['slots'])
        print(json.dumps({'date': day, 'shop_id': args.shop,
            'snapshot_generated_at': data['generated_at'],
            'blocking_records': len(issues),
            'reasons': dict(Counter(i['reason'] for i in issues)),
            'records': issues}, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, OSError, StopIteration):
        raise SystemExit('No valid saved snapshot for this DS/date. No private response printed.')
