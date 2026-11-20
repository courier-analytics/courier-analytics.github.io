"""Read distinct ZIZ/service pairs for DS9107; no courier or order-level export."""
import csv,io,json,re
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from services_pilot import chart_data
from superset_access import api
from prepare_openvpn import private_write
ROOT=Path('/opt/courier-analytics/private')
FIELDS=('delivery_type','name_service')

def query(first,last):
    if first>last or (last-first).days>1:raise ValueError('Use one or two calendar days')
    return {'datasource':{'id':3035,'type':'table'},'force':True,'result_format':'json','result_type':'full',
      'queries':[{'columns':list(FIELDS),'metrics':[{'expressionType':'SQL','sqlExpression':'min(1)','label':'pair_present','hasCustomLabel':True}],
      'granularity':'date_supply','time_range':first.isoformat()+'T00:00:00 : '+(last+timedelta(days=1)).isoformat()+'T00:00:00',
      'filters':[{'col':'shopno','op':'IN','val':[9107]}],'row_limit':10000,'is_timeseries':False,
      'orderby':[['delivery_type',True],['name_service',True]],'extras':{'where':'','having':''},'post_processing':[]}]}

def pairs(rows):
    if len(rows)>=10000:raise ValueError('Possible row limit; no partial report saved')
    result=set()
    for row in rows:
        if not set(FIELDS)<=set(row) or row.get('pair_present')!=1:raise ValueError('Unverified grouped response')
        ziz=row['delivery_type'];service=row['name_service']
        if not isinstance(ziz,str):continue
        ziz=ziz.strip()
        if not re.fullmatch(r'ЗиЗ\s*[-–—]\s*\d+',ziz,re.IGNORECASE):continue
        if not isinstance(service,str) or not service.strip():raise ValueError('Missing service label for ZIZ')
        result.add((ziz,service.strip()))
    def key(pair):return (int(re.search(r'\d+',pair[0]).group()),pair[0].casefold(),pair[1].casefold())
    return sorted(result,key=key)

def collect(opener,token,first,last):
    first=date.fromisoformat(first);last=date.fromisoformat(last)
    if last>datetime.now(ZoneInfo('Europe/Moscow')).date():raise ValueError('Future period')
    payload=query(first,last)
    code,data=api(opener,'/api/v1/dataset/3035',token=token)
    columns={c['column_name'] for c in data.get('result',{}).get('columns',[])} if isinstance(data,dict) else set()
    if code!=200 or not set(FIELDS+('shopno','date_supply'))<=columns:raise ValueError('Source schema not verified')
    code,data=chart_data(opener,token,payload)
    blocks=data.get('result') if isinstance(data,dict) else None
    if code!=200 or not isinstance(blocks,list) or len(blocks)!=1:raise ValueError('ZIZ query failed')
    block=blocks[0]
    if block.get('error') or block.get('status') not in (None,'success') or not isinstance(block.get('data'),list):raise ValueError('ZIZ source response incomplete')
    result=pairs(block['data'])
    output={'shop_id':9107,'period_from':first.isoformat(),'period_to':last.isoformat(),
        'observed_at':datetime.now(ZoneInfo('Europe/Moscow')).isoformat(),
        'date_basis':'date_supply; Moscow calendar days; all order statuses',
        'rows':[{'ziz':z,'service':s} for z,s in result]}
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    name=f'ziz-services-9107-{first}-{last}'
    private_write(ROOT/(name+'.json'),json.dumps(output,ensure_ascii=False,indent=2))
    text=io.StringIO();writer=csv.writer(text);writer.writerow(['ЗиЗ','Сервис']);writer.writerows(result)
    private_write(ROOT/(name+'.csv'),'\ufeff'+text.getvalue())
    print('ЗиЗ\tСервис',flush=True)
    for ziz,service in result:print(ziz+'\t'+service,flush=True)
    if not result:print('В выбранном периоде ЗиЗ с заказами не обнаружены.',flush=True)
    print('Private report: '+name+'.csv',flush=True)
    return output
