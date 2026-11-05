"""Read evidenced cancellation history for bookings in the immutable daily plan."""
from collections import defaultdict
from datetime import datetime, timezone
from subprocess import SubprocessError
from urllib.parse import urlencode
from calculate_metrics import timestamp
from enrich_slots import api_get


def collect(day, shop, plan, slots, token, proxy):
    if not plan or not plan.get('verified') or plan.get('date') != day:
        return []
    frozen = timestamp(plan.get('captured_at'))
    if frozen is None:
        return []
    present = {(s['slot_type'], s['slot_id'], p['courier_id'])
               for s in slots for p in s['couriers']}
    missing = defaultdict(list)
    for slot in plan['slots']:
        for person in slot['couriers']:
            if (slot['slot_type'], slot['slot_id'], person['courier_id']) not in present:
                missing[(slot['slot_type'], slot['slot_id'])].append((slot, person))
    result = []
    for (kind, identity), bookings in missing.items():
        if kind not in ('limited', 'manual') or type(identity) is not int or identity <= 0:
            continue
        path = ('/v1/schedules/limited-slots/'+str(identity)+'/reservations/history' if kind == 'limited'
                else '/v1/schedules/slots/'+str(identity)+'/history?'+urlencode({'slot_type':kind}))
        try:
            history = api_get(path, token, proxy)
            items = history.get('items', [])
            if not isinstance(items, list):continue
            for slot, person in bookings:
                matches = []
                for version in items:
                    if (str(version.get('slot_id')) != str(identity) or version.get('date') != day or
                        str(version.get('shopno')) != str(shop) or
                        version.get('time_from') != slot['time_from'] or version.get('time_to') != slot['time_to']):
                        continue
                    for booking in version.get('couriers', []):
                        if str(booking.get('id')) != person['courier_id']:continue
                        start, end = timestamp(booking.get('date_start')), timestamp(booking.get('date_end'))
                        if start is None or end is None or not start <= frozen < end <= datetime.now(timezone.utc):continue
                        matches.append({'verified':True,'date':day,'slot_id':identity,'slot_type':kind,
                            'courier_id':person['courier_id'],
                            'name':booking.get('fio') if isinstance(booking.get('fio'),str) else None,
                            'planned_from':slot['time_from'],'planned_to':slot['time_to'],
                            'removed_at':end.isoformat(),
                            'removed_by':booking.get('deleted_by') if isinstance(booking.get('deleted_by'),str) else None,
                            'source':'native_booking_history','captured_at':frozen.isoformat()})
                if len(matches) == 1:result.append(matches[0])
        except (RuntimeError, ValueError, KeyError, TypeError, AttributeError, OSError, SubprocessError):
            # Missing/ambiguous history never establishes cancellation or no-show.
            continue
    return result
