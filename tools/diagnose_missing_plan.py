"""Read-only evidence for frozen bookings missing from current slots; no metric writes."""
import argparse,json
from datetime import date,datetime,timezone
from pathlib import Path
from urllib.parse import urlencode
from report_tomorrow import collect
from enrich_slots import api_get,fetch,ApiError,atomic_json
from proxy_config import configured_proxy
from check_plan_capture import load_plan
from discover_scopes import first


def differences(plan_slots,current_slots):
    current={(s['slot_type'],s['slot_id'],p['courier_id']):(s,p) for s in current_slots for p in s['couriers']}
    output=[]
    for slot in plan_slots:
        for person in slot['couriers']:
            key=slot['slot_type'],slot['slot_id'],person['courier_id']
            if key not in current:
                output.append({'slot_id':slot['slot_id'],'slot_type':slot['slot_type'],'courier_id':person['courier_id'],
                    'planned_from':slot['time_from'],'planned_to':slot['time_to'],
                    'other_current_bookings':[{'slot':s,'person':p} for k,(s,p) in current.items() if k[2]==key[2]]})
    return output


def redact(value):
    if isinstance(value,dict):
        return {k:redact(v) for k,v in value.items() if not any(x in k.lower() for x in ('password','token','authorization','cookie','secret'))}
    if isinstance(value,list):return [redact(v) for v in value]
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--date',required=True);parser.add_argument('--shop',type=int,choices=[7745,5818],default=7745)
    args=parser.parse_args();date.fromisoformat(args.date)
    private=Path('/opt/courier-analytics/private');plan=load_plan(private/'plans'/f'plan-{args.date}.json',args.date)
    if not plan:raise ValueError('Verified frozen plan absent')
    original=next(s for s in plan['shops'] if s['shop_id']==args.shop)
    token=json.loads(Path('/root/curator-session.json').read_text())['token'];proxy=configured_proxy()
    shop=collect(args.date,[args.shop],token,proxy)[0]
    if not shop['available']:raise ValueError('Current shop slots unavailable')
    missing=differences(original['slots'],shop['slots'])
    result={'date':args.date,'shop_id':args.shop,'observed_at':datetime.now(timezone.utc).isoformat(),
            'plan_started_at':plan['started_at'],'plan_completed_at':plan['completed_at'],
            'plan_slots':original['slots'],'current_slots':shop['slots'],'missing':missing,'histories':{},'raw_slots':[]}
    if missing:
        query=urlencode({'date_from':args.date,'date_to':args.date,'shops':args.shop})
        try:result['courier_schedule_source']=redact(api_get('/v1/couriers/schedules/slots?'+query,token,proxy))
        except (RuntimeError,ValueError):result['courier_schedule_source_error']='source_unavailable'
    scopes=set()
    for item in missing:
        if item['slot_type']=='limited' and str(item['slot_id']) not in result['histories']:
            try:result['histories'][str(item['slot_id'])]=redact(api_get('/v1/schedules/limited-slots/'+str(item['slot_id'])+'/reservations/history',token,proxy))
            except ApiError as error:result['histories'][str(item['slot_id'])]={'http_status':error.status}
            except (RuntimeError,ValueError):result['histories'][str(item['slot_id'])]={'error':'source_unavailable'}
        for slot in shop['slots']:
            if (slot['slot_type'],slot['slot_id'])==(item['slot_type'],item['slot_id']):scopes.add((slot['scope_kind'],slot['scope_id']))
    wanted={str(m['slot_id']) for m in missing}
    for kind,identity in scopes:
        try:
            raw=fetch((args.date,kind,identity,'all'),token,proxy)
            raw=raw if isinstance(raw,list) else raw.get('slots',raw.get('items',[]))
            result['raw_slots'].extend(redact(row) for row in raw if str(first(row,'slot_id','limited_slot_id','id')) in wanted)
        except (RuntimeError,ValueError,TypeError):result['raw_source_error']='source_unavailable'
    path=private/f'missing-plan-{args.date}-{args.shop}.json';atomic_json(path,result)
    print(json.dumps({'date':args.date,'shop_id':args.shop,'missing_bookings':len(missing),'history_slots':len(result['histories']),'file':str(path)},ensure_ascii=False,indent=2))
    print('Read-only diagnostic saved privately. Frozen plan, metrics and timers unchanged.')

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError,RuntimeError,StopIteration):raise SystemExit('Diagnostic failed; private source details hidden.')
