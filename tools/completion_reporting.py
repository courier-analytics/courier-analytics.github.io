"""Collect metric seven with overnight shifts assigned by actual end date."""
from datetime import date, datetime, timedelta
import json

from audit_sources import sanitize_slot
from calculate_metrics import MOSCOW, current_slot_completion, period, timestamp
from enrich_slots import atomic_json, fetch, source_status
from shift_reporting_day import reporting_day
from overnight_completion import resolve as resolve_overnight
from dashboard_shops import SHOPS

BASIS = 'slot_completion_by_actual_night_end_date'
FIRST_DAYS = {shop: config['first_day'] for shop, config in SHOPS.items()}


def is_night(slot):
    return period(slot)[1].date().isoformat() != slot['date']


def choose(slots, day):
    selected, original_nights = [], {}
    for slot in sorted(slots, key=lambda s: s['date']):
        people = []
        night = is_night(slot)
        for person in slot['couriers']:
            if reporting_day(slot, person) != day:
                continue
            start = timestamp(person.get('shift_start'))
            identity = person['courier_id'], start
            if start is not None and identity in original_nights and slot['date'] > original_nights[identity]:
                continue
            if night and start is not None:
                original_nights[identity] = slot['date']
            people.append(person)
        if people:
            selected.append({**slot, 'couriers': people})
    return selected


def pending(slot):
    return any(not timestamp(p.get('shift_end')) and
               source_status(p.get('shift_status')) != 'no_show' for p in slot['couriers'])


def collect(day, shop, scope_config, current_slots, token, proxy, state_dir, now=None):
    now = now or datetime.now(MOSCOW)
    path = state_dir/'completion-night-state'/f'{shop}.json'
    state = json.loads(path.read_text()) if path.exists() else {'days': {}}
    scopes = [('shopno', shop)] + [('cluster_id', int(c)) for c in scope_config['cluster_ids']]
    # Bootstrap origins once; keep polling open nights even if several days old.
    cursor = date.fromisoformat(FIRST_DAYS[shop])-timedelta(days=1)
    while cursor < date.fromisoformat(day):
        origin = cursor.isoformat()
        cached = state['days'].get(origin)
        scope_ids = [list(s) for s in scopes]
        if cached is None or cached.get('scopes') != scope_ids or any(pending(s) for s in cached['slots']):
            nights = []
            for kind, scope_id in scopes:
                payload = fetch((origin, kind, scope_id, 'limited'), token, proxy)
                rows = payload if isinstance(payload, list) else payload.get('slots', payload.get('items'))
                if not isinstance(rows, list):
                    raise ValueError('Incomplete historical night scope')
                for raw in rows:
                    slot = sanitize_slot(raw, origin, kind, scope_id)
                    if slot['slot_type'] != 'limited':
                        raise ValueError('Unexpected limited-source type')
                    if is_night(slot):
                        nights.append(slot)
            nights, _ = resolve_overnight(nights, token, proxy, now)
            state['days'][origin] = {'scopes': scope_ids, 'slots': nights}
            atomic_json(path, state)
        cursor += timedelta(days=1)
    limited = [s for s in current_slots if s['slot_type'] == 'limited']
    state['days'][day] = {'scopes': [list(s) for s in scopes],
                          'slots': [s for s in limited if is_night(s)]}
    atomic_json(path, state)
    history = [s for origin, saved in state['days'].items() if origin < day for s in saved['slots']]
    selected = choose(history+limited, day)
    result = current_slot_completion(selected, now)
    result['basis'] = BASIS
    return result, {'night_records_included': sum(len(s['couriers']) for s in selected if is_night(s)),
                    'open_night_records_excluded': sum(
                        not timestamp(p.get('shift_end')) for s in history+limited if is_night(s)
                        for p in s['couriers']),
                    'reporting_rule': 'actual_night_end_date_moscow'}
