"""Compare five-day scheduled participants with observed attendance, without PII."""
import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from audit_sources import audit
from discover_scopes import TARGETS
from enrich_slots import atomic_json, source_status


def summarize(observations, day):
    days = [(date.fromisoformat(day)-timedelta(days=n)).isoformat() for n in range(5)]
    if len(observations) != 5 or {o['date'] for o in observations} != set(days):
        raise ValueError('Five complete distinct daily snapshots required')
    summaries = []
    for identity in TARGETS:
        snapshots = [next((s for s in o['shops'] if s['shop_id'] == identity), None)
                     for o in observations]
        if any(s is None for s in snapshots):
            summaries.append({'shop_id': identity, 'available': False, 'reason': 'incomplete_scope'})
            continue
        scheduled, attended = set(), set()
        by_scope = {}
        for snapshot in snapshots:
            for slot in snapshot['slots']:
                scope = (slot.get('scope_kind'), slot.get('scope_id'))
                scope_people = by_scope.setdefault(scope, set())
                for person in slot['couriers']:
                    scheduled.add(person['courier_id'])
                    scope_people.add(person['courier_id'])
                    if source_status(person.get('shift_status')) in ('on_time', 'early', 'late') or person.get('shift_start'):
                        attended.add(person['courier_id'])
        current = next(s for o in observations if o['date'] == day
                       for s in o['shops'] if s['shop_id'] == identity)
        booked_today = {c['courier_id'] for s in current['slots'] for c in s['couriers']}
        summaries.append({'shop_id': identity, 'available': True,
                          'scheduled_unique_5d': len(scheduled),
                          'attendance_observed_unique_5d': len(attended),
                          'scheduled_without_observed_attendance_5d': len(scheduled-attended),
                          'with_slot_on_selected_day': len(booked_today),
                          'scope_breakdown': [
                              {'kind': kind, 'id': scope_id, 'unique_5d': len(people),
                               'unique_only_in_this_scope': len(people-set().union(*[
                                   other for key, other in by_scope.items() if key != (kind, scope_id)]))}
                              for (kind, scope_id), people in sorted(by_scope.items(), key=lambda item: str(item[0]))],
                          'selected_day_share_of_scheduled_base': round(len(booked_today)/len(scheduled)*100, 2) if scheduled else None})
    return {'date_from': min(days), 'date_to': day, 'days': 5,
            'basis': 'scheduled_participants_including_selected_day', 'shops': summaries}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', default=datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat())
    parser.add_argument('--proxy', default=os.environ.get('COURIER_PROXY_URL', 'socks5h://127.0.0.1:18080'))
    parser.add_argument('--saved', action='store_true', help='Analyze saved snapshots without API access')
    args = parser.parse_args()
    try:
        selected = date.fromisoformat(args.date)
        token = None if args.saved else json.loads(Path('/root/curator-session.json').read_text())['token']
        if not args.saved and (not isinstance(token, str) or not token or '\n' in token or '\r' in token):
            raise ValueError('Invalid session')
        root = Path('/opt/courier-analytics/private/active-base-audit')
        observations = []
        for offset in range(5):
            day = (selected-timedelta(days=offset)).isoformat()
            folder = root/day
            if not args.saved:
                print('Checking '+day+'...', flush=True)
                audit(day, token, args.proxy, folder, extra_details=False)
            observations.append(json.loads((folder/'all-shops-observations.json').read_text()))
        report = summarize(observations, args.date)
        atomic_json(root/'summary.json', report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print('Audit only: public metrics and timers unchanged.')
    except (ValueError, KeyError, TypeError, OSError, RuntimeError):
        raise SystemExit('Five-day audit incomplete; public metrics unchanged. No private response printed.')
