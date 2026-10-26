"""Daily unique-courier metrics with explicit roster and frozen-plan prerequisites."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from enrich_slots import source_status

MOSCOW = ZoneInfo('Europe/Moscow')
SLOT_ATTENDANCE_BASIS = 'current_limited_bookings_unique_couriers'
SLOT_COMPLETION_BASIS = 'current_limited_all_shifts_site_10min_tolerance'


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None else None
    except (ValueError, AttributeError, TypeError):
        return None


def metric(numerator=None, denominator=None, reason=None, basis=None):
    return {'value': round(numerator/denominator*100, 2)
            if reason is None and denominator else None,
            'numerator': numerator, 'denominator': denominator,
            'reason': reason or (None if denominator else 'zero_denominator'),
            'basis': basis}


def period(slot):
    def minutes(text):
        hour, minute = map(int, text[:5].split(':'))
        if hour < 0 or hour > 24 or minute < 0 or minute > 59 or (hour == 24 and minute):
            raise ValueError('Invalid planned time')
        return hour*60+minute
    start, end = minutes(slot['time_from']), minutes(slot['time_to'])
    if end <= start:
        end += 1440
    midnight = datetime.fromisoformat(slot['date']).replace(tzinfo=MOSCOW)
    return midnight+timedelta(minutes=start), midnight+timedelta(minutes=end)


def calculate(slots, day, roster=None, plan=None):
    if any(s['date'] != day for s in slots):
        raise ValueError('Mixed dates in daily metrics')
    limited = [s for s in slots if s['slot_type'] == 'limited']
    capacity = sum(s['capacity'] for s in limited)
    booked = sum(len(s['couriers']) for s in limited)
    output = {'slot_fill': metric(booked, capacity, basis='limited_slot_places')}
    booked_ids = {c['courier_id'] for s in slots for c in s['couriers']}
    if roster and roster.get('verified') is True:
        assigned = set(roster['courier_ids'])
        output['shift_marked'] = metric(len(booked_ids & assigned), len(assigned), basis='all_assigned_unique_couriers')
    else:
        output['shift_marked'] = metric(reason='assigned_roster_not_verified')
    plan_metrics = ('planned_attendance', 'planned_late', 'unplanned_work', 'planned_completion')
    if not plan or plan.get('verified') is not True or plan.get('date') != day:
        output.update({key: metric(reason='frozen_plan_missing') for key in plan_metrics})
        # User-selected fallback: facts in current limited-slot cards, rather
        # than an assertion that these bookings existed on the preceding day.
        output.update(current_slot_attendance(limited))
        output['planned_completion'] = current_slot_completion(limited)
        return output
    current = {(s['slot_type'], s['slot_id'], c['courier_id']): (s, c)
               for s in slots for c in s['couriers']}
    expected = {}
    for slot in plan['slots']:
        if slot['date'] != day:
            raise ValueError('Mixed plan dates')
        for person in slot['couriers']:
            identity = person['courier_id']
            key = slot['slot_type'], slot['slot_id'], identity
            if key in expected:
                raise ValueError('Duplicate planned booking')
            expected[key] = slot
    planned = {key[2] for key in expected}
    if any(key not in current for key in expected):
        output.update({key: metric(reason='planned_booking_missing_from_current_data') for key in plan_metrics})
        return output
    if any(current[key][0]['time_from'] != slot['time_from'] or
           current[key][0]['time_to'] != slot['time_to'] for key, slot in expected.items()):
        output.update({key: metric(reason='planned_slot_times_changed') for key in plan_metrics})
        return output
    states = {key: source_status(current[key][1]['shift_status']) for key in expected}
    if 'unknown' in states.values():
        output.update({key: metric(reason='unknown_planned_shift_status') for key in plan_metrics})
        return output
    arrived_states = {'on_time', 'early', 'late'}
    arrived = {key[2] for key, state in states.items() if state in arrived_states}
    late = {key[2] for key, state in states.items() if state == 'late'}
    basis = 'frozen_plan_unique_couriers'
    output['planned_attendance'] = metric(len(arrived), len(planned), basis=basis)
    output['planned_late'] = metric(len(late), len(arrived), basis=basis)
    all_states = [source_status(c['shift_status']) for s in slots for c in s['couriers']]
    worked = {c['courier_id'] for s in slots for c in s['couriers']
              if source_status(c['shift_status']) in arrived_states}
    manual_worked = {c['courier_id'] for s in slots if s['slot_type'] == 'manual'
                     for c in s['couriers'] if source_status(c['shift_status']) in arrived_states}
    output['unplanned_work'] = metric(reason='unknown_shift_status') if 'unknown' in all_states else metric(
        len(manual_worked-planned), len(worked), basis='manual_work_without_frozen_plan')
    # The website's BM/zM flags leaving early when the gap exceeds 10 minutes.
    completion, unfinished_facts = {}, False
    for key, slot in expected.items():
        identity = key[2]
        if states[key] == 'no_show':
            completion[identity] = False
            continue
        end = timestamp(current[key][1]['shift_end'])
        if states[key] == 'expected' or end is None:
            unfinished_facts = True
            continue
        _, planned_end = period(slot)
        completed = end >= planned_end-timedelta(minutes=10)
        completion[identity] = completion.get(identity, True) and completed
    output['planned_completion'] = metric(reason='shift_end_or_final_status_missing') if unfinished_facts else metric(
        sum(completion.get(identity, False) for identity in planned), len(planned),
        basis='frozen_plan_all_shifts_site_10min_tolerance')
    return output


def current_slot_attendance(limited):
    people = [(c['courier_id'], source_status(c.get('shift_status')))
              for slot in limited for c in slot['couriers']]
    keys = ('planned_attendance', 'planned_late')
    if any(state == 'unknown' for _, state in people):
        return {key: metric(reason='unknown_shift_status', basis=SLOT_ATTENDANCE_BASIS) for key in keys}
    booked = {identity for identity, _ in people}
    arrived = {identity for identity, state in people if state in ('on_time', 'early', 'late')}
    late = {identity for identity, state in people if state == 'late'}
    return {'planned_attendance': metric(len(arrived), len(booked), basis=SLOT_ATTENDANCE_BASIS),
            'planned_late': metric(len(late), len(arrived), basis=SLOT_ATTENDANCE_BASIS)}


def current_slot_completion(limited, now=None):
    now = now or datetime.now(MOSCOW)
    completion = {}
    for slot in limited:
        if not slot['couriers']:
            continue
        try:
            start, planned_end = period(slot)
        except (ValueError, KeyError, TypeError, AttributeError):
            return metric(reason='shift_end_or_final_status_missing', basis=SLOT_COMPLETION_BASIS)
        for person in slot['couriers']:
            identity = person['courier_id']
            state = source_status(person.get('shift_status'))
            if state == 'unknown':
                return metric(reason='unknown_shift_status', basis=SLOT_COMPLETION_BASIS)
            if state == 'no_show':
                if planned_end > now:
                    return metric(reason='shift_end_or_final_status_missing', basis=SLOT_COMPLETION_BASIS)
                completion[identity] = False
                continue
            end = timestamp(person.get('shift_end'))
            if state == 'expected' or end is None or end > now or end < start-timedelta(days=1):
                return metric(reason='shift_end_or_final_status_missing', basis=SLOT_COMPLETION_BASIS)
            completed = end >= planned_end-timedelta(minutes=10)
            completion[identity] = completion.get(identity, True) and completed
    return metric(sum(completion.values()), len(completion), basis=SLOT_COMPLETION_BASIS)
