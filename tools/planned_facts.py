"""Conservative matching of frozen bookings to current source facts, without changing slots."""
from collections import Counter,defaultdict
from enrich_slots import source_status


def index(slots,plan_slots):
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
    return current
