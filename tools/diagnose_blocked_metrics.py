"""Explain blocking plan and completion facts from private source snapshots."""
import argparse,json
from datetime import datetime,timedelta
from pathlib import Path
from calculate_metrics import MOSCOW,period,timestamp,current_slot_completion
from completion_reporting import choose,is_night
from diagnose_missing_plan import differences
from enrich_slots import atomic_json,source_status
from metric_exclusions import load,filter_slots


def completion_blockers(slots,now=None):
    now=now or datetime.now(MOSCOW)
    result=[]
    for slot in slots:
        start,end=period(slot)
        for person in slot['couriers']:
            state=source_status(person.get('shift_status'))
            actual=timestamp(person.get('shift_end'))
            reason=None
            if state=='unknown':reason='unknown_shift_status'
            elif state=='no_show':continue
            elif state=='expected':
                if person.get('shift_start') or person.get('shift_end'):reason='still_expected'
                else:continue
            elif actual is None:reason='actual_end_missing'
            elif actual>now:reason='actual_end_in_future'
            elif actual<start-timedelta(days=1):reason='actual_end_invalid'
            if reason:
                result.append({'slot_id':slot['slot_id'],'slot_type':slot['slot_type'],
                    'date':slot['date'],'planned_from':slot['time_from'],'planned_to':slot['time_to'],
                    'courier_id':person['courier_id'],'name':person.get('name'),
                    'shift_status':person.get('shift_status'),'shift_start':person.get('shift_start'),
                    'shift_end':person.get('shift_end'),'reason':reason})
    return result


def explain(private,day,shop):
    observations=json.loads((private/'all-shops/all-shops-observations.json').read_text())
    source=next(s for s in observations['shops'] if s['shop_id']==shop)
    ids=load(private,day,shop)
    slots=filter_slots(source['slots'],ids)
    planpath=private/'plans'/('plan-'+day+'.json')
    plan=json.loads(planpath.read_text()) if planpath.exists() else {}
    planned=next((s['slots'] for s in plan.get('shops',[]) if s['shop_id']==shop),[])
    statepath=private/'completion-night-state'/f'{shop}.json'
    state=json.loads(statepath.read_text()) if statepath.exists() else {'days':{}}
    saved_nights={(s['slot_type'],s['slot_id']):s for s in state['days'].get(day,{}).get('slots',[])}
    slots=[saved_nights.get((s['slot_type'],s['slot_id']),s) for s in slots]
    slots=filter_slots(slots,ids)
    history=[s for origin,saved in state['days'].items() if origin<day for s in saved['slots']]
    selected=filter_slots(choose(history+[s for s in slots if s['slot_type']=='limited'],day),ids)
    from planned_facts import index as index_planned_facts
    plan_slots=filter_slots(planned,ids)
    facts=index_planned_facts(slots,plan_slots,[c for c in source.get('plan_cancellations',[]) if c.get('date')==day and c.get('courier_id') not in ids])
    missing=differences(plan_slots,slots)
    unresolved=[m for m in missing if (m['slot_type'],m['slot_id'],m['courier_id']) not in facts]
    cancelled=sum(bool(facts.get((m['slot_type'],m['slot_id'],m['courier_id']),(None,{}))[1].get('plan_cancellation')) for m in missing)
    return {'date':day,'shop_id':shop,'excluded_count':len(ids),
        'missing_plan_bookings':missing,'unresolved_plan_bookings':unresolved,
        'matched_rebooked_facts':len(missing)-len(unresolved)-cancelled,
        'confirmed_cancelled_bookings':cancelled,
        'completion_metric':current_slot_completion(selected),
        'completion_blockers':completion_blockers(selected),
        'unresolved_nights_not_assigned_to_report_day':[
            {'date':s['date'],'slot_id':s['slot_id'],'courier_id':p['courier_id'],
             'name':p.get('name'),'shift_start':p.get('shift_start'),'shift_status':p.get('shift_status')}
            for s in filter_slots(history+slots,ids) if is_night(s)
            for p in s['couriers'] if timestamp(p.get('shift_end')) is None],
        'source_slots':slots}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',required=True);parser.add_argument('--shop',type=int,default=7745)
    args=parser.parse_args()
    private=Path('/opt/courier-analytics/private')
    result=explain(private,args.date,args.shop)
    path=private/f'blocked-metrics-{args.date}-{args.shop}.json';atomic_json(path,result)
    print(json.dumps({'date':args.date,'shop_id':args.shop,'missing_plan_bookings':len(result['missing_plan_bookings']),
        'unresolved_plan_bookings':len(result['unresolved_plan_bookings']),
        'matched_rebooked_facts':result['matched_rebooked_facts'],
        'confirmed_cancelled_bookings':result['confirmed_cancelled_bookings'],
        'completion_blockers':len(result['completion_blockers']),'file':str(path)},ensure_ascii=False))
