"""Recover missing overnight ends only from a demonstrably identical shift."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta

from audit_sources import sanitize_slot
from calculate_metrics import MOSCOW, period, timestamp
from enrich_slots import fetch, source_status


def match_end(original, candidates, now):
    start = timestamp(original.get('shift_start'))
    if start is None:
        return None, 'original_shift_start_missing_or_unzoned'
    matching = [c for c in candidates if c['courier_id'] == original['courier_id']
                and timestamp(c.get('shift_start')) == start
                and source_status(c.get('shift_status')) != 'no_show']
    ends = {timestamp(c.get('shift_end')) for c in matching}
    ends.discard(None)
    ends = {end for end in ends if start <= end <= now}
    if len(ends) > 1:
        return None, 'conflicting_next_day_ends'
    if not ends:
        return None, 'same_shift_end_not_found_next_day'
    return next(iter(ends)).isoformat(), 'matched_same_courier_and_actual_shift_start'


def resolve(slots, token, proxy, now=None):
    now = now or datetime.now(MOSCOW)
    resolved = deepcopy(slots)
    cache, reasons = {}, Counter()
    recovered = 0
    for slot in resolved:
        if slot['slot_type'] != 'limited':
            continue
        try:
            _, end = period(slot)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        next_day = (datetime.fromisoformat(slot['date']).date()+timedelta(days=1)).isoformat()
        if end.date().isoformat() != next_day or end > now:
            continue
        for person in slot['couriers']:
            if person.get('shift_end') or source_status(person.get('shift_status')) == 'no_show':
                continue
            key = next_day, slot['scope_kind'], slot['scope_id']
            if key not in cache:
                try:
                    payload = fetch((*key, 'all'), token, proxy)
                    rows = payload if isinstance(payload, list) else payload.get('slots', payload.get('items'))
                    if not isinstance(rows, list):
                        raise ValueError('Incomplete next-day list')
                    next_slots = [sanitize_slot(row, *key) for row in rows]
                    cache[key] = [c for s in next_slots for c in s['couriers']]
                except (RuntimeError, ValueError, KeyError, TypeError):
                    cache[key] = None
            if cache[key] is None:
                reasons['next_day_source_unavailable'] += 1
                continue
            actual_end, reason = match_end(person, cache[key], now)
            reasons[reason] += 1
            if actual_end:
                person['shift_end'] = actual_end
                person['shift_end_source_date'] = next_day
                recovered += 1
    return resolved, {'recovered_records': recovered, 'reasons': dict(reasons)}
