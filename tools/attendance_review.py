"""Private attendance evidence for a responsible person's review, never 1C writes.

This report does not approve a measure or call a limit-changing worker.
"""
import argparse,csv,hashlib,io,json,os
from datetime import date,datetime,time
from pathlib import Path
from zoneinfo import ZoneInfo
from audit_sources import audit
from enrich_slots import atomic_json,source_status
from proxy_config import configured_proxy
START=date(2026,11,22)
SHOPS=(8889,7745,9107)
TZ=ZoneInfo('Europe/Moscow')


def proposed_measure(status,late_seconds,has_start=False,shop_id=None):
    if status=='no_show':
        return {'operation':'set','value':1} if not has_start else None
    if status!='late' or late_seconds is None:return None
    if shop_id==8889:
        if late_seconds>180*60:return {'operation':'set','value':1}
        if late_seconds>30*60:return {'operation':'subtract','value':2}
        return None
    if late_seconds>90*60:return {'operation':'subtract','value':2}
    if late_seconds>30*60:return {'operation':'subtract','value':1}
    return None


def review_rows(observations,day):
    day=date.fromisoformat(day)
    if day<START:raise ValueError('No measures before 2026-11-22')
    output=[]
    for shop in observations['shops']:
        if shop['shop_id'] not in SHOPS:continue
        for slot in shop['slots']:
            if slot['date']!=day.isoformat():raise ValueError('Source day mismatch')
            planned=datetime.fromisoformat(day.isoformat()+'T'+slot['time_from']).replace(tzinfo=TZ)
            for person in slot['couriers']:
                text=(person.get('shift_status') or '').strip()
                status=source_status(text)
                value=person.get('shift_start');seconds=None
                if value:
                    actual=datetime.fromisoformat(value.replace('Z','+00:00'))
                    if actual.tzinfo is None:raise ValueError('Arrival timezone missing')
                    seconds=(actual-planned).total_seconds()
                # Missing timestamp or conflicting facts must remain evidence
                # requiring investigation, never an automatically issued measure.
                measure=proposed_measure(status,seconds,bool(value),shop['shop_id'])
                unresolved=status=='no_show' and bool(value) or status=='late' and seconds is None
                if measure is None and not unresolved:continue
                cid=person['courier_id']
                if not str(cid).isdigit():raise ValueError('Courier identity missing')
                seed='|'.join(map(str,[day,shop['shop_id'],slot['scope_kind'],slot['scope_id'],slot['slot_type'],slot['slot_id'],cid]))
                output.append({'event_id':hashlib.sha256(seed.encode()).hexdigest(),
                    'date':day.isoformat(),'shop_id':shop['shop_id'],'courier_id':str(cid),'name':person.get('name',''),
                    'slot_id':slot['slot_id'],'planned_start':planned.isoformat(),'source_status':text,
                    'actual_start':value,'late_seconds':seconds,'proposed_measure':measure,
                    'review_state':'pending_review','unresolved_facts':bool(unresolved),
                    'current_limit':None,'target_limit':None,'applied':False})
    # A repeated booking across slots/shops is highlighted for human review.
    counts={}
    for row in output:counts[row['courier_id']]=counts.get(row['courier_id'],0)+1
    for row in output:row['multiple_bookings_for_courier']=counts[row['courier_id']]>1
    ids=[r['event_id'] for r in output]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate source event')
    return output


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--date',default=datetime.now(TZ).date().isoformat())
    p.add_argument('--private-dir',type=Path,default=Path('/opt/courier-analytics/private'))
    args=p.parse_args();day=date.fromisoformat(args.date)
    if not START<=day<=datetime.now(TZ).date():raise ValueError('Report date outside allowed window')
    os.umask(0o077)
    token=json.loads(Path('/root/curator-session.json').read_text())['token']
    folder=args.private_dir/'attendance-review'/day.isoformat();folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    summary=audit(day.isoformat(),token,configured_proxy(),folder/'source',extra_details=False)
    verified={s['shop_id'] for s in summary['shops'] if s.get('scope_verified')}
    if not set(SHOPS)<=verified:raise ValueError('Not all three shop scopes verified')
    observations=json.loads((folder/'source/all-shops-observations.json').read_text())
    rows=review_rows(observations,args.date)
    report={'date':args.date,'observed_at':datetime.now(TZ).isoformat(),'shops':list(SHOPS),
            'human_review_required':True,'one_c_writes_enabled':False,'rows':rows}
    atomic_json(folder/'pending-review.json',report)
    text=io.StringIO();writer=csv.writer(text)
    writer.writerow(['ДС','ID курьера','ФИО','Начало слота, МСК','Статус источника','Опоздание, минут','Предложенная мера','Проверить факты','Повторные записи','Состояние'])
    for r in rows:
        measure=r['proposed_measure'];label='Не определена'
        if measure:label='Установить 1 заказ' if measure['operation']=='set' else 'Уменьшить текущий лимит на '+str(measure['value'])
        writer.writerow([r['shop_id'],r['courier_id'],r['name'],r['planned_start'],r['source_status'],
            '' if r['late_seconds'] is None else round(r['late_seconds']/60,2),label,r['unresolved_facts'],r['multiple_bookings_for_courier'],'Ожидает проверки ответственным'])
    (folder/'pending-review.csv').write_text('\ufeff'+text.getvalue())
    print('Attendance review report saved privately:',folder/'pending-review.csv')
    print('No courier limit was changed. Every case requires responsible-person review.')

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as error:
        raise SystemExit('Attendance evidence collection failed: '+type(error).__name__+'. No limits changed.')
