"""Private order-type export for a payroll reconciliation. Never sends messages."""
import json
from pathlib import Path
from services_pilot import chart_data
from prepare_openvpn import private_write


def collect(opener,token,courier_ids):
    if not courier_ids or len(courier_ids)>20 or any(type(x) is not int or x<=0 for x in courier_ids):
        raise ValueError('Specify 1-20 positive courier IDs')
    fields=['id_order','id_general','id_courier','id_courier_type','courier_type','courier_kontr','id_courier_kontr']
    def payload(columns,metrics,offset=0,limit=5000):
        return {'datasource':{'id':3035,'type':'table'},'force':True,'result_format':'json','result_type':'full',
          'queries':[{'columns':columns,'metrics':metrics,'granularity':'date_supply',
          'time_range':'2026-11-04T00:00:00 : 2026-11-18T00:00:00',
          'filters':[{'col':'shopno','op':'IN','val':[9107]}, {'col':'id_courier','op':'IN','val':courier_ids}],
          'row_limit':limit,'row_offset':offset,'is_timeseries':False,
          'orderby':[['id_order',True]] if not metrics else [],'extras':{'where':'','having':''},'post_processing':[]}]}
    def read(q):
        code,data=chart_data(opener,token,q)
        blocks=data.get('result') if isinstance(data,dict) else None
        if code!=200 or not isinstance(blocks,list) or len(blocks)!=1 or blocks[0].get('error') or blocks[0].get('status') not in ('success',None):
            print('Payroll type export HTTP '+str(code),flush=True)
            raise ValueError('Payroll type query failed')
        result=blocks[0].get('data')
        if not isinstance(result,list):raise ValueError('Invalid payroll source response')
        return result
    metric={'expressionType':'SQL','sqlExpression':'count()','label':'source_rows','hasCustomLabel':True}
    expected=read(payload([],[metric],limit=1))[0]['source_rows']
    if type(expected) is not int or not 0<expected<50000:raise ValueError('Unexpected payroll source size')
    rows=[];previous=None
    while len(rows)<expected:
        page=read(payload(fields,[],offset=len(rows)))
        if not page:raise ValueError('Payroll export truncated')
        marker=(page[0]['id_order'],page[-1]['id_order'])
        if marker==previous:raise ValueError('Payroll pagination ignored')
        previous=marker;rows.extend(page)
    after=read(payload([],[metric],limit=1))[0]['source_rows']
    if len(rows)!=expected or after!=expected:raise ValueError('Payroll source changed while exporting')
    output={'dataset':3035,'shop':9107,'courier_ids':courier_ids,'complete':True,
            'expected':expected,'received':len(rows),'after':after,'rows':rows}
    target=Path('/opt/courier-analytics/private/pay-types-9107.json')
    private_write(target,json.dumps(output,ensure_ascii=False,indent=2))
    print('Payroll type export verified: '+str(len(rows))+' rows; saved privately as pay-types-9107.json',flush=True)
