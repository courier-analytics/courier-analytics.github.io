"""Collect all dashboard DS scopes in one read-only, privacy-preserving audit."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from discover_scopes import discover, first
from enrich_slots import ApiError, api_get, atomic_json, fetch, optional, source_status


def shape(value, depth=0):
    if depth > 4:
        return type(value).__name__
    if isinstance(value, dict):
        return {key: shape(item, depth+1) for key, item in value.items()}
    if isinstance(value, list):
        return {'count': len(value), 'first': shape(value[0], depth+1) if value else None}
    return type(value).__name__


def sanitize_slot(raw, day, kind, scope_id):
    identity = first(raw, 'slot_id', 'limited_slot_id', 'id')
    slot_type = str(first(raw, 'type', 'slot_type', 'slotType') or '').lower()
    if slot_type not in ('limited', 'manual'):
        raise ValueError('Unrecognized slot type')
    actual_scope = first(raw, 'shopno_cluster_id', 'shopno', 'shop_id')
    if actual_scope is None or int(actual_scope) != scope_id:
        raise ValueError('API returned a different scope')
    if raw.get('date') and str(raw['date'])[:10] != day:
        raise ValueError('API returned a different day')
    people = raw.get('couriers')
    if not isinstance(people, list):
        raise ValueError('Slot courier details absent')
    clean = []
    for person in people:
        if person.get('status') == 'cancelled':
            continue
        courier_id = optional(person, 'id')
        if not courier_id or not courier_id.isdigit():
            raise ValueError('Invalid courier identity')
        clean.append({'courier_id': courier_id,
                      'shift_status': optional(person, 'shift_status', 'shiftStatus'),
                      'shift_start': optional(person, 'shift_start', 'shiftStart'),
                      'shift_end': optional(person, 'shift_end', 'shiftEnd'),
                      'booked_at': optional(person, 'booking_date', 'bookingDate', 'booked_at')})
    if len({c['courier_id'] for c in clean}) != len(clean):
        raise ValueError('Duplicate courier in one slot')
    return {'slot_id': int(identity), 'slot_type': slot_type, 'date': day,
            'scope_kind': kind, 'scope_id': scope_id,
            'time_from': raw.get('time_from'), 'time_to': raw.get('time_to'),
            'capacity': first(raw, 'capacity', 'courier_limits'),
            'occupied': first(raw, 'occupied', 'booked', 'total_occupied'),
            'couriers': clean}


def audit(day, token, proxy, directory, extra_details=True):
    config = discover(api_get('/v1/shops', token, proxy), api_get('/v1/clusters', token, proxy))
    private = {'date': day, 'generated_at': datetime.now(timezone.utc).isoformat(),
               'scope_config': config, 'shops': []}
    public = {'date': day, 'shops': []}
    for shop in config['shops']:
        summary = {'shop_id': shop['shop_id'], 'scope_verified': shop['scope_verified'],
                   'cluster_ids': shop['cluster_ids']}
        public['shops'].append(summary)
        if not shop['scope_verified']:
            summary['reason'] = shop['reason']
            continue
        slots, seen = [], set()
        scope_error = None
        for kind, identity in [('shopno', shop['shop_id'])] + [('cluster_id', c) for c in shop['cluster_ids']]:
            try:
                payload = fetch((day, kind, identity, 'all'), token, proxy)
            except ApiError as error:
                if error.status not in (403, 404):
                    raise
                scope_error = f'slots_http_{error.status}'
                break
            raw = payload if isinstance(payload, list) else payload.get('slots', payload.get('items'))
            if not isinstance(raw, list):
                raise ValueError('Unknown slot list format')
            for item in raw:
                slot = sanitize_slot(item, day, kind, identity)
                key = (slot['slot_type'], slot['slot_id'])
                if key in seen:
                    raise ValueError('Repeated slot across scopes')
                seen.add(key)
                slots.append(slot)
        if scope_error:
            summary.update(scope_verified=False, reason=scope_error)
            shop.update(scope_verified=False, reason=scope_error)
            continue
        limited = [s for s in slots if s['slot_type'] == 'limited']
        if any(type(s['capacity']) is not int or s['capacity'] < 0 for s in limited):
            raise ValueError('Invalid limited-slot capacity')
        if any(type(s['occupied']) is not int or s['occupied'] != len(s['couriers']) for s in limited):
            raise ValueError('Occupied count differs from limited-slot courier list')
        capacity = sum(s['capacity'] for s in limited)
        booked = sum(len(s['couriers']) for s in limited)
        summary.update({'slots_by_type': dict(Counter(s['slot_type'] for s in slots)),
            'limited_places': capacity, 'limited_booked': booked,
            'fill_percent': round(booked/capacity*100, 2) if capacity else None,
            'unique_couriers_in_slots': len({c['courier_id'] for s in slots for c in s['couriers']}),
            'source_status_counts': dict(Counter(source_status(c['shift_status'])
                                                 for s in slots for c in s['couriers'])),
            'records_missing_shift_end': sum(not c['shift_end'] for s in slots for c in s['couriers'])})
        # The site's primary-token roster/schedules API. Do not call the 1C endpoint
        # with a wrong token or infer a full assigned roster from slot participants.
        query = urlencode({'date_from': day, 'date_to': day, 'shops': shop['shop_id']})
        if extra_details:
            try:
                roster = api_get('/v1/couriers/schedules/slots?' + query, token, proxy)
                summary['roster_response_shape'] = shape(roster)
            except ApiError as error:
                summary['roster_http_error'] = error.status
        sample = next((s for s in limited if len(s['couriers']) > 1), None) if extra_details else None
        if sample:
            try:
                history = api_get(f"/v1/schedules/limited-slots/{sample['slot_id']}/reservations/history", token, proxy)
                summary['reservation_history_shape'] = shape(history)
            except ApiError as error:
                summary['reservation_history_http_error'] = error.status
        private['shops'].append({'shop_id': shop['shop_id'], 'slots': slots})
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    atomic_json(directory/'all-shops-observations.json', private)
    atomic_json(directory/'discovered-scopes.json', config)
    atomic_json(directory/'source-audit-summary.json', public)
    return public


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, default=Path('/root/curator-session.json'))
    parser.add_argument('--proxy', default=os.environ.get('COURIER_PROXY_URL', 'socks5h://127.0.0.1:18080'))
    parser.add_argument('--date', default=datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat())
    parser.add_argument('--output-dir', type=Path, default=Path('/opt/courier-analytics/private/audit'))
    args = parser.parse_args()
    try:
        from datetime import date
        date.fromisoformat(args.date)
        token = json.loads(args.session.read_text())['token']
        if not isinstance(token, str) or '\n' in token or '\r' in token:
            raise ValueError('Invalid token')
        print(json.dumps(audit(args.date, token, args.proxy, args.output_dir), ensure_ascii=False, indent=2))
    except RuntimeError as error:
        raise SystemExit(str(error))
    except (ValueError, KeyError, TypeError, OSError) as error:
        import traceback
        frame = traceback.extract_tb(error.__traceback__)[-1]
        raise SystemExit('Source audit failed validation; existing dashboard and timer unchanged. '
                         f'{type(error).__name__} at {frame.name}:{frame.lineno}')
