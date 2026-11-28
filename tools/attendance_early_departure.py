"""Confirmed DS8889 early finishes; missing facts never imply a departure."""
from calculate_metrics import MOSCOW,period,timestamp,cutoff_end
from enrich_slots import source_status


def evidence(slot,person,now):
    if source_status(person.get('shift_status')) not in ('on_time','early','late'):return None
    try:planned_start,planned_end=period(slot)
    except (ValueError,KeyError,TypeError,AttributeError):return None
    start=timestamp(person.get('shift_start'));end=timestamp(person.get('shift_end'))
    if start is None or end is None or cutoff_end(person) is not None:return None
    if not (start<planned_end and planned_start<end and start<end<=now):return None
    seconds=(planned_end-end).total_seconds()
    if seconds<3600:return None
    return {'planned_end':planned_end.isoformat(),'actual_end':end.isoformat(),'early_departure_seconds':seconds}


def review_rows(observations,day,now):
    import hashlib
    rows=[]
    for shop in observations['shops']:
        if shop['shop_id']!=8889:continue
        for slot in shop['slots']:
            if slot['date']!=day:raise ValueError('Source day mismatch')
            for person in slot['couriers']:
                facts=evidence(slot,person,now)
                if facts is None:continue
                cid=str(person['courier_id'])
                if not cid.isdigit():raise ValueError('Courier identity missing')
                booking='|'.join(map(str,[day,8889,slot['scope_kind'],slot['scope_id'],slot['slot_type'],slot['slot_id'],cid]))
                seed='early_departure|'+booking
                planned_start,_=period(slot)
                rows.append({'event_id':hashlib.sha256(seed.encode()).hexdigest(),'case_kind':'early_departure','booking_event_id':hashlib.sha256(booking.encode()).hexdigest(),
                    'date':timestamp(person['shift_end']).astimezone(MOSCOW).date().isoformat(),'source_date':day,'shop_id':8889,'courier_id':cid,'name':person.get('name',''),'slot_id':slot['slot_id'],
                    'planned_start':planned_start.isoformat(),'actual_start':person['shift_start'],
                    'source_status':person.get('shift_status',''),'late_seconds':None,
                    'proposed_measure':{'operation':'set','value':1},'review_state':'pending_review',
                    'unresolved_facts':False,'current_limit':None,'target_limit':None,'applied':False,**facts})
    return rows
