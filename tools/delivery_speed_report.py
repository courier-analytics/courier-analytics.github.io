"""Read-only weekly delivery durations, deduplicated by order; output aggregates only."""
import json
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from services_pilot import chart_data
from superset_access import api
from matryoshka_history import metric
from prepare_openvpn import private_write
TZ=ZoneInfo('Europe/Moscow')
PAGE=5000

def stamp(value):
    if not value:return None
    moment=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    return moment if moment.tzinfo else moment.replace(tzinfo=TZ)

def summarize(rows,shop,start,end):
    unique={}
    for row in rows:
        if str(row['shopno'])!=str(shop):raise ValueError('Wrong shop in report')
        identity=str(row['id_order'])
        if not identity.isdigit():raise ValueError('Invalid order identity')
        evidence=tuple(row.get(k) for k in ('date_order','date_delivery_start','date_delivered'))
        if identity in unique and unique[identity]!=evidence:raise ValueError('Conflicting duplicate order')
        unique[identity]=evidence
    totals={};daily={}
    for order,began,delivered in unique.values():
        finish=stamp(delivered)
        if finish is None or not start<=finish.astimezone(TZ).date()<end:raise ValueError('Delivery outside report period')
        key=finish.astimezone(TZ).date().isoformat()
        bucket=daily.setdefault(key,{'orders':0});bucket['orders']+=1
        for name,value in (('order_to_delivery',order),('courier_delivery_leg',began)):
            one=totals.setdefault(name,{'seconds':0,'valid_orders':0,'missing_start':0,'invalid_duration':0})
            day=bucket.setdefault(name,{'seconds':0,'valid_orders':0,'missing_start':0,'invalid_duration':0})
            begin=stamp(value)
            if begin is None:
                one['missing_start']+=1;day['missing_start']+=1;continue
            seconds=(finish-begin).total_seconds()
            if seconds<0:
                one['invalid_duration']+=1;day['invalid_duration']+=1;continue
            for counter in (one,day):counter['seconds']+=seconds;counter['valid_orders']+=1
    def finish_metrics(metrics):
        for key in ('order_to_delivery','courier_delivery_leg'):
            item=metrics.get(key)
            if item is not None:item['average_minutes']=round(item['seconds']/item['valid_orders']/60,2) if item['valid_orders'] else None
    finish_metrics(totals)
    for bucket in daily.values():finish_metrics(bucket)
    return {'shop':shop,'from_inclusive':start.isoformat(),'to_exclusive':end.isoformat(),'timezone':'Europe/Moscow',
            'successful_unique_orders':len(unique),'source_rows':len(rows),'metrics':totals,'by_day':dict(sorted(daily.items())),
            'definitions':{'order_to_delivery':'date_order → date_delivered','courier_delivery_leg':'date_delivery_start → date_delivered'},
            'averaging':'Arithmetic mean per unique successfully delivered order, not mean of daily averages.'}

def collect(opener,token,shop,start_text,end_text):
    shop=int(shop);start=date.fromisoformat(start_text);end=date.fromisoformat(end_text)
    if not 1<=shop<=999999 or not 0<(end-start).days<=31:raise ValueError('Invalid report scope')
    fields=['id_order','shopno','date_order','date_delivery_start','date_delivered']
    code,definition=api(opener,'/api/v1/dataset/3035',token=token)
    source=definition.get('result',{}) if isinstance(definition,dict) else {}
    if code!=200 or not set(fields)<={c['column_name'] for c in source.get('columns',[])}:raise ValueError('Required delivery fields unavailable')
    def query(columns,metrics,offset=0,limit=PAGE):
        return {'datasource':{'id':3035,'type':'table'},'force':True,'result_format':'json','result_type':'full','queries':[{
            'columns':columns,'metrics':metrics,'filters':[{'col':'shopno','op':'IN','val':[shop]},{'col':'status_name','op':'IN','val':['Успешно завершен']}],
            'granularity':'date_delivered','time_range':(start-timedelta(days=2)).isoformat()+'T00:00:00 : '+(end+timedelta(days=2)).isoformat()+'T00:00:00',
            'extras':{'where':"date_delivered IS NOT NULL AND date_delivered >= toDateTime('"+start.isoformat()+" 00:00:00', 'Europe/Moscow') AND date_delivered < toDateTime('"+end.isoformat()+" 00:00:00', 'Europe/Moscow')",'having':''},'row_limit':limit,'row_offset':offset,
            'orderby':[['id_order',True]] if not metrics else [],'is_timeseries':False,'post_processing':[]}]}
    def fetch(payload):
        code,answer=chart_data(opener,token,payload)
        blocks=answer.get('result') if isinstance(answer,dict) else None
        if code!=200 or not isinstance(blocks,list) or len(blocks)!=1 or blocks[0].get('error') or blocks[0].get('status') not in (None,'success'):
            raise ValueError('Delivery query failed')
        rows=blocks[0].get('data')
        if not isinstance(rows,list):raise ValueError('Invalid delivery response')
        return rows
    def size():
        rows=fetch(query([],[metric('count()','source_rows')],limit=1))
        if len(rows)!=1 or type(rows[0].get('source_rows')) is not int or not 0<=rows[0]['source_rows']<=200000:raise ValueError('Invalid report row count')
        return rows[0]['source_rows']
    expected=size();rows=[]
    columns=['id_order','shopno']+[{'expressionType':'SQL','sqlExpression':"formatDateTime("+field+", '%Y-%m-%dT%H:%i:%S', 'Europe/Moscow')",'label':field} for field in fields[2:]]
    while len(rows)<expected:
        batch=fetch(query(columns,[],offset=len(rows),limit=min(PAGE,expected-len(rows))))
        if not batch or len(rows)+len(batch)>expected:raise ValueError('Truncated or changing report')
        rows.extend(batch)
        print('Delivery report rows:',len(rows),'/',expected,flush=True)
    if size()!=expected:raise ValueError('Source changed during export')
    report=summarize(rows,shop,start,end)
    target=Path('/opt/courier-analytics/private')/f'delivery-speed-{shop}-{start}-{end}.json'
    private_write(target,json.dumps(report,ensure_ascii=False,indent=2))
    print('DELIVERY SPEED REPORT:',json.dumps(report,ensure_ascii=False,indent=2),flush=True)
