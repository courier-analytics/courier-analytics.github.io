"""Read-only native Superset metric pilot, never sends Telegram messages."""
import json, re, time
from pathlib import Path
from superset_access import api
from prepare_openvpn import private_write

def chart_data(opener,token,payload):
    code,data=api(opener,'/api/v1/chart/data',payload,token)
    if code!=202:return code,data
    result=data.get('result') if isinstance(data,dict) else None
    jobs=result if isinstance(result,list) else [result]
    keys=[job.get('cache_key') for job in jobs if isinstance(job,dict)]
    if len(keys)!=1 or not isinstance(keys[0],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',keys[0]):
        return code,data
    for _ in range(8):
        time.sleep(2)
        polled,answer=api(opener,'/api/v1/chart/data/'+keys[0],token=token)
        if polled==200:return polled,answer
        if polled not in (202,400,404):return polled,answer
    return code,data

def collect(opener,token):
    result={'date':'2026-11-09','shop_id':9107,'source_dataset':3035,'datasets':[],'samples':[]}
    for identity in (3035,5438):
        code,data=api(opener,'/api/v1/dataset/'+str(identity),token=token)
        source=data.get('result') if isinstance(data,dict) else None
        print('Report dataset '+str(identity)+' HTTP: '+str(code),flush=True)
        if code!=200 or not isinstance(source,dict):continue
        result['datasets'].append({'id':identity,
          'columns':[{k:c.get(k) for k in ('column_name','type','expression')} for c in source.get('columns',[])],
          'metrics':[{k:m.get(k) for k in ('metric_name','verbose_name','expression','d3format')} for m in source.get('metrics',[])]})
    source=next((s for s in result['datasets'] if s['id']==3035),None)
    names={m['metric_name'] for m in source['metrics']} if source else set()
    metrics=['qty_orders_delivered','qty_couriers','share_collection_delay_all','share_all_0_sla_offline','avg_order_time']
    if set(metrics)<=names and {'shopno','date_supply','delivery_type_group'}<={c['column_name'] for c in source['columns']}:
        for start,end in [('2026-11-08','2026-11-09'),('2026-11-09','2026-11-10')]:
            payload={'datasource':{'id':3035,'type':'table'},'force':False,'result_format':'json','result_type':'full','queries':[{
                'columns':['shopno'],'metrics':metrics,'row_limit':20,'is_timeseries':False,
                'filters':[{'col':'shopno','op':'IN','val':[9107]},
                    {'col':'delivery_type_group','op':'IN','val':['Курьеры','Такси']},
                    {'col':'date_supply','op':'TEMPORAL_RANGE','val':start+'T00:00:00 : '+end+'T00:00:00'}],
                'extras':{'where':'','having':''},'orderby':[],'post_processing':[]}]}
            code,data=chart_data(opener,token,payload)
            blocks=data.get('result') if isinstance(data,dict) else None
            safe=[]
            if code==200 and isinstance(blocks,list):
                for b in blocks:
                    if not b.get('error') and b.get('status') in ('success',None):
                        safe.extend({k:r.get(k) for k in ['shopno']+metrics} for r in b.get('data',[]))
            result['samples'].append({'date':start,'http_status':code,'rows':safe,'pending':code==202,'response_fields':sorted(data) if isinstance(data,dict) else [],'result_fields':sorted(data['result']) if isinstance(data,dict) and isinstance(data.get('result'),dict) else []})
            print('Report sample '+start+' HTTP: '+str(code)+'; rows='+str(len(safe)),flush=True)
    target=Path('/opt/courier-analytics/private/services-report-pilot.json')
    private_write(target,json.dumps(result,ensure_ascii=False,indent=2))
    print('Private pilot saved: '+str(target),flush=True)
