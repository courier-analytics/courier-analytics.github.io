"""Private, paginated Superset export with explicit period and count checks."""
import gzip
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from superset_access import api
from services_pilot import chart_data
from prepare_openvpn import private_write
from staffing.core import SHOPS, START, END

ROOT=Path('/opt/courier-analytics/private')
FIELDS=['id_general','id_order','shopno','status_name','delivery_type_group','delivery_type',
        'courier','id_courier','courier_type','id_courier_type','name_tt']
DATES=['date_order','date_supply','date_delivery_start','date_delivered','order_closed_offline_dttm']
PAGE=5000


def response(opener,token,payload):
    code,data=chart_data(opener,token,payload)
    blocks=data.get('result') if isinstance(data,dict) else None
    if code!=200 or not isinstance(blocks,list) or len(blocks)!=1 or blocks[0].get('error') or blocks[0].get('status') not in ('success',None):
        private_write(ROOT/'staffing-export-error.json',json.dumps({'http_status':code,'response':data},ensure_ascii=False))
        raise ValueError('Staffing query failed; details saved privately')
    rows=blocks[0].get('data')
    if not isinstance(rows,list):raise ValueError('Invalid staffing rows')
    return rows


def collect(opener,token):
    definitions=[]; matched=False
    for identity in (20281,20445,20450):
        code,data=api(opener,'/api/v1/chart/'+str(identity),token=token)
        chart=data.get('result') if isinstance(data,dict) else None
        if code!=200 or not isinstance(chart,dict):continue
        params=chart.get('params') or '{}'
        params=json.loads(params) if isinstance(params,str) else params
        datasource=params.get('datasource') or chart.get('datasource_id')
        if str(datasource).split('__')[0]=='3035':matched=True
        definitions.append({'id':identity,'name':chart.get('slice_name'),'datasource':datasource})
    if not matched:raise ValueError('Could not verify Time by orders chart uses dataset 3035')
    code,data=api(opener,'/api/v1/dataset/3035',token=token)
    source=data.get('result') if isinstance(data,dict) else None
    names={c['column_name'] for c in source.get('columns',[])} if isinstance(source,dict) else set()
    if code!=200 or not set(FIELDS+DATES)<=names:raise ValueError('Staffing source columns missing')
    # A 2-day buffer allows delivery-start attribution near reporting boundaries.
    bounds=(START-timedelta(days=2)).isoformat()+'T00:00:00 : '+(END+timedelta(days=2)).isoformat()+'T00:00:00'
    def payload(columns,metrics,shop,offset=0,limit=PAGE):
        return {'datasource':{'id':3035,'type':'table'},'force':True,'result_format':'json','result_type':'full',
          'queries':[{'columns':columns,'metrics':metrics,'granularity':'date_supply','time_range':bounds,
            'filters':[{'col':'shopno','op':'IN','val':[shop]}],
            'row_limit':limit,'row_offset':offset,'is_timeseries':False,
            'orderby':[['id_order',True]] if not metrics else [],
            'extras':{'where':'','having':''},'post_processing':[]}]}
    count_metric={'expressionType':'SQL','sqlExpression':'count()','label':'source_rows','hasCustomLabel':True}
    columns=FIELDS+[{'expressionType':'SQL','sqlExpression':"formatDateTime("+field+", '%Y-%m-%dT%H:%i:%S.%f')",'label':field} for field in DATES]
    all_rows=[];checks=[]
    for shop in SHOPS:
        expected=response(opener,token,payload([], [count_metric],shop,limit=1))[0]['source_rows']
        if type(expected) is not int or expected<0 or expected>1000000:raise ValueError('Unexpected export size')
        offset=0;previous=None
        while offset<expected:
            page=response(opener,token,payload(columns,[],shop,offset, min(PAGE,expected-offset)))
            if not page:raise ValueError('Export truncated before source count')
            if any(int(r['shopno'])!=shop for r in page):raise ValueError('Shop filter failed')
            marker=(page[0]['id_order'],page[-1]['id_order'])
            if marker==previous:raise ValueError('Pagination ignored by server')
            previous=marker;offset+=len(page);all_rows.extend(page)
            if offset>expected:raise ValueError('Export changed while paging')
            print('Staffing export DS '+str(shop)+': '+str(offset)+'/'+str(expected),flush=True)
        after=response(opener,token,payload([], [count_metric],shop,limit=1))[0]['source_rows']
        if after!=expected:raise ValueError('Source count changed during export; retry')
        checks.append({'shop':shop,'expected':expected,'received':offset,'after':after})
    output={'schema_version':1,'observed_at':datetime.now(ZoneInfo('Europe/Moscow')).isoformat(),
        'period':'2026-10-12..2026-11-15','query_range':bounds,'source_dataset':3035,
        'charts':definitions,'source_definition':{k:source.get(k) for k in ('sql','main_dttm_col')},
        'date_column_types':{c['column_name']:c.get('type') for c in source.get('columns',[]) if c['column_name'] in DATES},'complete':True,'checks':checks,'rows':all_rows,
        'datetime_basis':'source wall-clock strings; interpreted as Moscow for this report'}
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=ROOT)
    try:
        with os.fdopen(fd,'wb') as raw:
            with gzip.GzipFile(fileobj=raw,mode='wb') as packed:
                packed.write(json.dumps(output,ensure_ascii=False).encode())
        os.replace(temp,ROOT/'staffing-orders-910-914.json.gz')
    finally:
        if os.path.exists(temp):os.unlink(temp)
    print('Staffing export verified and saved privately: staffing-orders-910-914.json.gz',flush=True)
