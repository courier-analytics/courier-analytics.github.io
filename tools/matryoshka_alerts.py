"""Plan Matryoshka type-change notices from verified enrollment snapshots.

This module does not fetch credentials, send messages or modify courier types.
Counts must cover the full enrollment, not only orders assigned the current type.
"""
from datetime import datetime,timedelta
import hashlib,json

TYPES={'bike':(24,25,26,27),'auto':(28,29,30,31)}
TYPE_INDEX={code:(transport,index+1) for transport,codes in TYPES.items() for index,code in enumerate(codes)}

def stage(orders):
    if type(orders) is not int or orders<0:raise ValueError('Invalid delivered order count')
    if orders<100:return 1
    if orders<300:return 2
    if orders<600:return 3
    if orders<1000:return 4
    return None

def timestamp(value):
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('Timezone required')
    return parsed

def plan(snapshot,now,acknowledged=(),max_age_seconds=300):
    if now.tzinfo is None:raise ValueError('Timezone required')
    if snapshot.get('verified') is not True:raise ValueError('Unverified source snapshot')
    observed=timestamp(snapshot['observed_at'])
    if observed>now or now-observed>timedelta(seconds=max_age_seconds):raise ValueError('Stale source snapshot')
    seen=set();alerts=[];blocked=[];acknowledged=set(acknowledged)
    for person in snapshot['participants']:
        identity=person['courier_id'];enrollment=person['enrollment_id']
        if not isinstance(identity,str) or not identity.isdigit() or not isinstance(enrollment,str) or not enrollment:raise ValueError('Invalid enrollment identity')
        key=(identity,enrollment)
        if key in seen:raise ValueError('Duplicate enrollment')
        seen.add(key)
        start=timestamp(person['enrolled_at'])
        if start>observed:raise ValueError('Enrollment starts after source snapshot')
        if person.get('count_scope')!='delivered_since_enrollment' or person.get('current_type_verified') is not True:
            blocked.append({'courier_id':identity,'reason':'count_scope_or_current_type_unverified'});continue
        count=person['delivered_orders'];target=stage(count);current=person['current_type']
        if type(current) is not int or current not in TYPE_INDEX:
            blocked.append({'courier_id':identity,'reason':'not_a_matryoshka_type'});continue
        transport,current_stage=TYPE_INDEX[current]
        if target is None:
            event=hashlib.sha256(json.dumps([identity,enrollment,'completed']).encode()).hexdigest()
            if event not in acknowledged:
                alerts.append({'event_id':event,'kind':'completed','courier_id':identity,
                    'name':person.get('name') or identity,'orders':count,'from_type':current,
                    'to_type':None,'transport':transport,'observed_at':snapshot['observed_at'],
                    'text':f"Матрёшка завершена\n{person.get('name') or identity} · ID {identity}\nДоставлено с подключения: {count}\nНужно перевести курьера на обычный тип ({'Вело' if transport=='bike' else 'Авто'})."})
            continue
        if target<current_stage:
            blocked.append({'courier_id':identity,'reason':'count_below_current_stage_no_automatic_downgrade'});continue
        if target==current_stage:continue
        desired=TYPES[transport][target-1]
        event=hashlib.sha256(json.dumps([identity,enrollment,desired],ensure_ascii=True).encode()).hexdigest()
        if event in acknowledged:continue
        alerts.append({'event_id':event,'courier_id':identity,'name':person.get('name') or identity,
            'orders':count,'from_type':current,'to_type':desired,'stage':target,'transport':transport,
            'observed_at':snapshot['observed_at'],
            'text':f"Матрёшка: пора изменить тип курьера\n{person.get('name') or identity} · ID {identity}\nДоставлено с подключения: {count}\nЭтап {current_stage} → {target}\nТип {current} → {desired} ({'Вело' if transport=='bike' else 'Авто'})"})
    return {'alerts':alerts,'blocked':blocked}
