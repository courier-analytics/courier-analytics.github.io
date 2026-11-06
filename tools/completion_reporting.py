"""Collect metric seven with overnight shifts assigned by actual end date."""
from datetime import date, datetime, timedelta
import json

from audit_sources import sanitize_slot
from calculate_metrics import MOSCOW, current_slot_completion, period, timestamp, cutoff_end
from enrich_slots import atomic_json, fetch, source_status
from shift_reporting_day import reporting_day
from overnight_completion import resolve as resolve_overnight
from dashboard_shops import SHOPS

BASIS = 'slot_completion_arrived_by_actual_night_end_date'
FIRST_DAYS = {shop: config['first_day'] for shop, config in SHOPS.items()}


def is_night(slot):
    return period(slot)[1].date().isoformat() != slot['date']


def continuation_only(original, fragment, person):
    """A continuous work fact must not erase an additional limited booking."""
    if fragment['slot_type'] != 'limited':return True
    try:
        _,original_end=period(original)
        if 'time_from' in fragment:following_start,following_end=period(fragment)
        else:following_start,following_end=timestamp(fragment.get('planned_start')),timestamp(fragment.get('planned_end'))
    except (ValueError,KeyError,TypeError,AttributeError):return False
    end=timestamp(person.get('shift_end')) or cutoff_end(person)
    return (following_end is not None and following_end<=original_end) or (
        following_start is not None and end is not None and end<following_start)


def choose(slots, day):
    selected, original_nights = [], {}
    def fragment(identity,day,kind,number,scope_kind,scope_id,start,end):
        return identity,day,kind,number,scope_kind,scope_id,timestamp(start),timestamp(end)
    continued={fragment(p['courier_id'],f['date'],f['slot_type'],f['slot_id'],f.get('scope_kind'),f.get('scope_id'),f.get('shift_start'),f.get('shift_end'))
        for s in slots if is_night(s) for p in s['couriers']
        for f in p.get('shift_continuation_facts',[]) if f['date']>s['date'] and continuation_only(s,f,f)}
    for slot in sorted(slots, key=lambda s: s['date']):
        people = []
        night = is_night(slot)
        for person in slot['couriers']:
            if fragment(person['courier_id'],slot['date'],slot['slot_type'],slot['slot_id'],slot.get('scope_kind'),slot.get('scope_id'),person.get('shift_start_raw') or person.get('shift_start'),person.get('shift_end_raw') or person.get('shift_end')) in continued:continue
            if reporting_day(slot, person) != day:
                continue
            start = timestamp(person.get('shift_start'))
            identity = person['courier_id'], start
            original=original_nights.get(identity)
            if original is not None and slot['date'] > original['date'] and continuation_only(original,slot,person):
                continue
            if night and start is not None:
                original_nights.setdefault(identity,slot)
            people.append(person)
        if people:
            selected.append({**slot, 'couriers': people})
    return selected


def pending(slot):
    return any((not timestamp(p.get('shift_end')) or cutoff_end(p) is not None) and
               source_status(p.get('shift_status')) != 'no_show' for p in slot['couriers'])


def collect(day, shop, scope_config, current_slots, token, proxy, state_dir, now=None, source_cache=None):
    now = now or datetime.now(MOSCOW)
    source_cache=source_cache if source_cache is not None else {}
    path = state_dir/'completion-night-state'/f'{shop}.json'
    state = json.loads(path.read_text()) if path.exists() else {'days': {}}
    scopes = [('shopno', shop)] + [('cluster_id', int(c)) for c in scope_config['cluster_ids']]
    # Bootstrap origins once; keep polling open nights even if several days old.
    cursor = date.fromisoformat(FIRST_DAYS[shop])-timedelta(days=1)
    while cursor < date.fromisoformat(day):
        origin = cursor.isoformat()
        cached = state['days'].get(origin)
        scope_ids = [list(s) for s in scopes]
        if cached is None or cached.get('cross_day_version')!=2 or cached.get('scopes') != scope_ids or any(pending(s) for s in cached['slots']):
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
            nights, _ = resolve_overnight(nights, token, proxy, now, source_cache=source_cache, scopes=scopes)
            state['days'][origin] = {'scopes': scope_ids, 'slots': nights, 'cross_day_version':2}
            atomic_json(path, state)
        cursor += timedelta(days=1)
    limited = [s for s in current_slots if s['slot_type'] == 'limited']
    limited,_=resolve_overnight(limited,token,proxy,now,source_cache=source_cache,scopes=scopes)
    state['days'][day] = {'scopes': [list(s) for s in scopes],
                          'slots': [s for s in limited if is_night(s)],'cross_day_version':2}
    atomic_json(path, state)
    history = [s for origin, saved in state['days'].items() if origin < day for s in saved['slots']]
    selected = choose(history+limited, day)
    result = current_slot_completion(selected, now)
    result['basis'] = BASIS
    return result, {'night_records_included': sum(len(s['couriers']) for s in selected if is_night(s)),
                    'stitched_end_records':sum(bool(p.get('shift_end_source_date')) for s in selected for p in s['couriers']),
                    'stitched_start_records':sum(bool(p.get('shift_start_source_date')) for s in selected for p in s['couriers']),
                    'open_night_records_excluded': sum(
                        not timestamp(p.get('shift_end')) for s in history+limited if is_night(s)
                        for p in s['couriers']),
                    'reporting_rule': 'actual_night_end_date_moscow'}
