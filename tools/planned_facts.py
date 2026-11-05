"""Conservative matching of frozen bookings to current source facts, without changing slots."""
from collections import Counter,defaultdict
from enrich_slots import source_status


def index(slots,plan_slots,cancellations=()):
    from calculate_metrics import timestamp,MOSCOW
    current={(s['slot_type'],s['slot_id'],p['courier_id']):(s,p)
             for s in slots for p in s['couriers']}
    by_person=defaultdict(list)
    for s in slots:
        for p in s['couriers']:by_person[p['courier_id']].append((s,p))
    count=Counter(p['courier_id'] for s in plan_slots for p in s['couriers'])
    for planned in plan_slots:
        for p in planned['couriers']:
            identity=p['courier_id'];key=planned['slot_type'],planned['slot_id'],identity
            if key in current or count[identity]!=1:continue
            candidates=by_person[identity]
            arrivals=[(s,person) for s,person in candidates
                if s['date']==planned['date'] and source_status(person.get('shift_status')) in {'on_time','early','late'}
                and timestamp(person.get('shift_start')) is not None]
            starts={timestamp(person['shift_start']) for s,person in arrivals}
            # One original booking and exactly one actual shift start identify a
            # rebooked courier. Evaluate lateness against the unchanged frozen time.
            all_starts={timestamp(person.get('shift_start')) for s,person in candidates if person.get('shift_start')}
            if len(starts)==1 and all_starts==starts:
                start=next(iter(starts)).astimezone(MOSCOW)
                if start.date().isoformat()==planned['date'] and start.time().isoformat()!='00:00:00':
                    source,person=arrivals[0]
                    current[key]=(planned,{**person,'plan_fact_source_slot_id':source['slot_id'],
                        'plan_fact_source_slot_type':source['slot_type'],
                        'plan_fact_note':'Фактический выход найден в перенесённой записи этого курьера. Опоздание считается от исходного времени зафиксированного плана.'})
                    continue
            # A removed booking alone never proves a no-show. Require explicit
            # same-day no-show in every surviving record, with no start/end facts.
            if (candidates and all(s['date']==planned['date'] and
                    source_status(person.get('shift_status'))=='no_show' and
                    not person.get('shift_start') and not person.get('shift_end')
                    for s,person in candidates)):
                source,person=candidates[0]
                current[key]=(planned,{**person,'plan_fact_source_slot_id':source['slot_id'],
                    'plan_fact_source_slot_type':source['slot_type'],
                    'plan_fact_note':'Запись из плана снята; в текущих записях этого курьера источник подтверждает «Не вышел». Исходный план сохранён.'})
    for planned in plan_slots:
        for person in planned['couriers']:
            identity=person['courier_id'];key=planned['slot_type'],planned['slot_id'],identity
            if key in current:continue
            # Conflicting actual work must still be investigated, even if the
            # original reservation was cancelled. History is not a work fact.
            if any(p.get('shift_start') or p.get('shift_end') for s,p in by_person[identity]):continue
            matches=[c for c in cancellations if c.get('verified') is True and
                (c.get('slot_type'),c.get('slot_id'),c.get('courier_id'))==key and
                c.get('date')==planned['date'] and c.get('planned_from')==planned['time_from'] and
                c.get('planned_to')==planned['time_to'] and c.get('source')=='native_booking_history']
            if len(matches)!=1:continue
            cancelled=matches[0]
            current[key]=(planned,{'courier_id':identity,'name':cancelled.get('name'),
                'shift_status':'Снятая смена','shift_start':None,'shift_end':None,
                'plan_cancellation':cancelled,
                'plan_fact_note':'Снятие подтверждено историей бронирования. Запись остаётся в исходном плане.'})
    return current
