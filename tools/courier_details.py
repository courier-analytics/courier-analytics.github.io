"""Private named metric groups, built from the same slots and plan as aggregate metrics."""
from collections import defaultdict
from datetime import datetime,timedelta
from calculate_metrics import period,timestamp,late_15_minutes,MOSCOW
from enrich_slots import source_status
ARRIVED={'early','on_time','late'}


def build(day,shop,metrics,roster=None,plan=None,completion_slots=None):
    slots=shop['slots'];names=dict((roster or {}).get('names',{}));current={};by_person=defaultdict(list)
    for slot in slots+(completion_slots or []):
        for person in slot['couriers']:
            identity=person['courier_id']
            if person.get('name'):names[identity]=person['name']
    def event(slot,person):
        start,end=period(slot);actual=timestamp(person.get('shift_start'));finish=timestamp(person.get('shift_end'))
        midnight=actual is not None and actual.astimezone(MOSCOW).time().isoformat()=='00:00:00'
        return {'slot_id':str(slot['slot_id']),'slot_type':slot['slot_type'],'scope':str(slot.get('name') or slot.get('scope_id','')),
            'planned_start':start.isoformat(),'planned_end':end.isoformat(),'actual_start':actual.isoformat() if actual else None,
            'actual_end':finish.isoformat() if finish else None,'status':person.get('shift_status') or 'Статус не передан',
            'late_seconds':max(0,int((actual-start).total_seconds())) if actual and not midnight else None,
            'note':person.get('plan_fact_note') or ('Проверить начало 00:00' if midnight else ''),
            **({'fact_source_slot_id':str(person['plan_fact_source_slot_id'])} if 'plan_fact_source_slot_id' in person else {})}
    for slot in slots:
        for person in slot['couriers']:
            key=(slot['slot_type'],slot['slot_id'],person['courier_id']);current[key]=(slot,person)
            by_person[person['courier_id']].append(event(slot,person))
    def rows(ids,events=None):
        return [{'courier_id':i,'name':names.get(i) or 'ФИО не передано источником','slots':(events or by_person).get(i,[])}
                for i in sorted(ids,key=lambda i:(names.get(i,'').casefold(),i))]
    result={}
    def put(key,groups,denominator=None,numerator=None,note=''):
        aggregate=metrics.get(key,{})
        ok=aggregate.get('value') is not None and denominator==aggregate.get('denominator') and numerator==aggregate.get('numerator')
        result[key]={'aggregate':aggregate,'groups':[{'title':title,'count':len(ids),'couriers':rows(ids,events)} for title,ids,events in groups],
                     'reconciled':ok,'note':note}
    base=set((roster or {}).get('courier_ids',[])) if (roster or {}).get('verified') is True else set()
    booked=set(by_person)
    if base:
        put('shift_marked',[('Записались',base&booked,None),('Не записались',base-booked,None),('Записи вне базы 1С — не входят в процент',booked-base,None)],len(base),len(base&booked))
    else:put('shift_marked',[],note='Персональный состав расчётной базы для этого снимка не подтверждён.')
    fill=[]
    for slot in slots:
        limited=slot['slot_type']=='limited';capacity=slot.get('capacity') if limited else None
        fill.append({'slot_id':str(slot['slot_id']),'scope':str(slot.get('name') or slot.get('scope_id','')),'slot_type':slot['slot_type'],
                     'planned_start':period(slot)[0].isoformat(),'planned_end':period(slot)[1].isoformat(),'capacity':capacity,
                     'occupied':len(slot['couriers']),'free':max(capacity-len(slot['couriers']),0) if limited else None,
                     'couriers':rows({p['courier_id'] for p in slot['couriers']})})
    result['slot_fill']={'aggregate':metrics['slot_fill'],'slots':fill,'groups':[], 'reconciled':True,
                         'note':'В процент входят только лимитированные слоты. Ручные показаны отдельно.'}
    frozen=bool(plan and plan.get('verified') is True)
    if frozen:
        from planned_facts import index as index_planned_facts
        current=index_planned_facts(slots,plan['slots'])
    expected={};planned_events=defaultdict(list)
    source_plan=plan['slots'] if frozen else [s for s in slots if s['slot_type']=='limited']
    for slot in source_plan:
        for person in slot['couriers']:
            key=(slot['slot_type'],slot['slot_id'],person['courier_id']);expected[key]=current.get(key)
            if key in current:planned_events[person['courier_id']].append(event(*current[key]))
            else:planned_events[person['courier_id']].append(event(slot,{'shift_status':'Запись из плана отсутствует в текущих данных'}))
    planned={key[2] for key in expected};arrived=set();no_show=set();waiting=set();unknown=set();late=set();late_unknown=set()
    states=defaultdict(list)
    for key,value in expected.items():
        state=source_status(value[1].get('shift_status')) if value else 'unknown';states[key[2]].append(state)
        if state in ARRIVED:
            arrived.add(key[2]);qualifies=late_15_minutes(*value)
            if qualifies is True:late.add(key[2])
            if qualifies is None:late_unknown.add(key[2])
    for i in planned-arrived:
        if 'unknown' in states[i]:unknown.add(i)
        elif all(s=='no_show' for s in states[i]):no_show.add(i)
        else:waiting.add(i)
    note='' if frozen else 'Фиксированного плана нет: показаны записи текущих лимитированных слотов.'
    put('planned_attendance',[('Вышли',arrived,planned_events),('Не вышли по статусу источника',no_show,planned_events),('Ожидаются',waiting,planned_events),('Нет подтверждённых данных',unknown,planned_events)],len(planned),len(arrived),note)
    put('planned_late',[('Опоздали от 15 минут',late,planned_events),('Без опоздания от 15 минут',arrived-late-late_unknown,planned_events),('Длительность не определена',late_unknown-late,planned_events)],len(arrived),len(late),note)
    worked={i for i,events in by_person.items() if any(source_status(e['status']) in ARRIVED for e in events)}
    if frozen:put('unplanned_work',[('Вышли вне плана',worked-planned,None),('Вышли по плану',worked&planned,None)],len(worked),len(worked-planned))
    else:put('unplanned_work',[('Фактически вышли',worked,None)],note='План накануне не сохранён: определить работу вне плана нельзя.')
    completion=defaultdict(list);completion_events=defaultdict(list);now=datetime.now(MOSCOW)
    for slot in completion_slots if completion_slots is not None else [s for s in slots if s['slot_type']=='limited']:
        start,end=period(slot)
        for person in slot['couriers']:
            i=person['courier_id'];state=source_status(person.get('shift_status'));finish=timestamp(person.get('shift_end'))
            if state=='no_show':answer=False if end<=now else None
            elif state=='unknown' or state=='expected' or finish is None or finish>now or finish<start-timedelta(days=1):answer=None
            else:answer=finish>=end-timedelta(minutes=10)
            completion[i].append(answer);completion_events[i].append(event(slot,person))
    done={i for i,v in completion.items() if all(x is True for x in v)}
    failed={i for i,v in completion.items() if any(x is False for x in v)}
    pending=set(completion)-done-failed
    put('planned_completion',[('Завершили учитываемые смены',done,completion_events),('Не завершили или ушли раньше',failed,completion_events),('Нет окончательных данных',pending,completion_events)],len(completion),len(done),'Ночные смены относятся к дате фактического завершения; допуск окончания — 10 минут.')
    return {'kind':'courier_metric_details','schema_version':1,'date':day,'shop_id':shop['shop_id'],'metrics':result}
