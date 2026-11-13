"""Private discovery of Superset Matryoshka fields; no notifications or type changes."""
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import json
from superset_access import api
from services_pilot import chart_data
from prepare_openvpn import private_write
SHOPS=(8889,7745,9107)

def employment(row):
    """User-confirmed rule: a missing partner denotes self-employment.

    Missing columns or a contradictory partner ID are not proof of this status.
    This describes the historical row, not necessarily the current courier card.
    """
    if not {'courier_kontr','id_courier_kontr'} <= row.keys():
        return 'unknown'
    def blank(value):
        return value is None or (isinstance(value,str) and value.strip() in ('','-','—','–'))
    if not blank(row['courier_kontr']):
        return 'partner'
    return 'self_employed' if blank(row['id_courier_kontr']) else 'unknown'

def inspect(opener,token,history=False):
    code,data=api(opener,'/api/v1/dataset/3035',token=token)
    source=data.get('result') if isinstance(data,dict) else None
    if code!=200 or not isinstance(source,dict):raise ValueError('Matryoshka dataset unavailable')
    fields=['id_courier','courier','shopno','id_courier_type','courier_type','id_courier_kontr','courier_kontr']
    names={c['column_name'] for c in source.get('columns',[])}
    if not set(fields+['date_delivered'])<=names:raise ValueError('Matryoshka fields unavailable')
    now=datetime.now(ZoneInfo('Europe/Moscow'))
    start=(now-timedelta(days=7)).date().isoformat();end=(now+timedelta(days=1)).date().isoformat()
    metrics=['qty_orders_delivered']+[
        {'expressionType':'SQL','sqlExpression':func+'(date_delivered)','label':label,'hasCustomLabel':True}
        for func,label in [('min','first_delivery_in_window'),('max','last_delivery_in_window')]]
    query={'datasource':{'id':3035,'type':'table'},'force':False,'result_format':'json','result_type':'full','queries':[{
        'columns':fields,'metrics':metrics,'row_limit':5000,'is_timeseries':False,'orderby':[],
        'granularity':'date_supply','time_range':start+'T00:00:00 : '+end+'T00:00:00',
        'filters':[{'col':'shopno','op':'IN','val':list(SHOPS)},
            {'col':'date_delivered','op':'TEMPORAL_RANGE','val':start+'T00:00:00 : '+end+'T00:00:00'}],
        'extras':{'where':'','having':''},'post_processing':[]}]}
    code,data=chart_data(opener,token,query)
    blocks=data.get('result') if isinstance(data,dict) else None
    if code!=200 or not isinstance(blocks,list):raise ValueError('Matryoshka query not ready; no alerts sent')
    rows=[]
    for block in blocks:
        if block.get('error') or block.get('status') not in ('success',None):raise ValueError('Matryoshka query failed')
        rows.extend({key:r.get(key) for key in fields+['qty_orders_delivered','first_delivery_in_window','last_delivery_in_window']} for r in block.get('data',[]))
    if len(rows)>=5000:raise ValueError('Matryoshka discovery may be truncated')
    for row in rows:
        row['employment_classification']=employment(row)
    output={'observed_at':now.isoformat(),'shops':list(SHOPS),'employment_type':None,
        'employment_rule':'User confirmed: blank partner means self-employed; conflicting partner ID remains unknown.',
        'window_start':start,'window_end':end,'rows':rows,
        'note':'Discovery only; employment filter intentionally disabled to verify source code mapping. Window counts are not enrollment counts; historical order types are not confirmed current types.'}
    codes=sorted({str(r.get('id_courier_kontr')) for r in rows})
    print('Matryoshka observed employment codes: '+json.dumps(codes),flush=True)
    for shop in SHOPS:
        print('Matryoshka DS '+str(shop)+' grouped rows: '+str(sum(str(r.get('shopno'))==str(shop) for r in rows)),flush=True)
    target=Path('/opt/courier-analytics/private/matryoshka-discovery.json')
    private_write(target,json.dumps(output,ensure_ascii=False,indent=2))
    print('Matryoshka discovery saved privately; rows='+str(len(rows))+'. No messages sent.',flush=True)

    if history:
        from matryoshka_history import collect
        collect(opener,token,output,source)
