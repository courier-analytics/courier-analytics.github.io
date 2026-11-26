"""Verified DS8889 connected 1C roster restricted to the requested type/employment policy."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from prepare_openvpn import private_write

SOURCE=Path('/opt/courier-contacts/connected/all.json')
BASIS='onec_connected_auto_velo_employment_3_5'
TZ=ZoneInfo('Europe/Moscow')

def normalize(data,day,now=None):
    now=now or datetime.now(timezone.utc)
    source=data.get('8889')
    if not isinstance(source,dict) or source.get('shop_id')!=8889 or source.get('verified') is not True or source.get('connected_only') is not True:
        raise ValueError('DS8889 connected export not verified')
    observed=datetime.fromisoformat(source['observed_at'])
    if observed.tzinfo is None or observed>now or (now-observed).total_seconds()>86400:
        raise ValueError('DS8889 connected export older than 24 hours or invalid')
    # A current roster cannot be backdated into historical denominators.
    if day!=now.astimezone(TZ).date().isoformat():raise ValueError('Historical DS8889 roster unavailable')
    rows=source.get('couriers')
    if not isinstance(rows,list) or not rows:raise ValueError('Empty connected export')
    ids=set();selected=set();names={}
    allowed={'авто','вело','авто курьер','вело курьер','автокурьер','велокурьер'}
    for row in rows:
        identity=row.get('courier_id')
        label=row.get('courier_type_name')
        employment=row.get('employment_type')
        if not isinstance(identity,str) or not identity.isdigit() or identity in ids or not isinstance(label,str) or not label.strip() or type(employment) is not int:
            raise ValueError('Incomplete or duplicate typed roster row')
        ids.add(identity)
        label=' '.join(re.sub(r'^\s*\d+\s*[-–]\s*','',label).casefold().split())
        if label in allowed and employment in (3,5):
            selected.add(identity)
            if isinstance(row.get('name'),str):names[identity]=row['name']
    if not selected:raise ValueError('No couriers match verified DS8889 type policy')
    return {'shop_id':8889,'date':day,'verified':True,'basis':BASIS,'courier_ids':sorted(selected),
            'count':len(selected),'names':names,'observed_at':source['observed_at'],
            'policy':{'courier_types':['Авто','Вело'],'employment_types':[3,5]}}

def load_for_day(directory,day,now=None,source=SOURCE):
    now=now or datetime.now(timezone.utc)
    archive=Path(directory)/'typed-8889'/f'{day}.json'
    if day==now.astimezone(TZ).date().isoformat():
        roster=normalize(json.loads(Path(source).read_text()),day,now)
        archive.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        private_write(archive,json.dumps(roster,ensure_ascii=False))
        return roster
    # Archives are written only by the verified current-day path above.
    saved=json.loads(archive.read_text())
    if saved.get('shop_id')!=8889 or saved.get('date')!=day or saved.get('basis')!=BASIS or saved.get('verified') is not True or saved.get('policy')!={'courier_types':['Авто','Вело'],'employment_types':[3,5]}:
        raise ValueError('Historical typed roster invalid')
    ids=saved.get('courier_ids')
    if not isinstance(ids,list) or not ids or len(set(ids))!=len(ids) or any(not isinstance(i,str) or not i.isdigit() for i in ids) or saved.get('count')!=len(ids):
        raise ValueError('Historical typed roster identities invalid')
    return saved

if __name__=='__main__':
    now=datetime.now(timezone.utc)
    data=json.loads(SOURCE.read_text())
    from collections import Counter
    record=data.get('8889',{})
    print('DS8889 export:',json.dumps({'observed_at':record.get('observed_at'),'verified':record.get('verified'),'connected_only':record.get('connected_only'),'type_employment_counts':dict(Counter(str(r.get('courier_type_name'))+' / '+str(r.get('employment_type')) for r in record.get('couriers',[])))},ensure_ascii=False))
    roster=normalize(data,now.astimezone(TZ).date().isoformat(),now)
    print('DS8889 verified denominator:',roster['count'],'couriers; policy: Auto/Velo and employment 3/5')
