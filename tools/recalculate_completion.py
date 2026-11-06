"""Recompute only metric seven from confirmed arrivals; retain all other metric data."""
import argparse,json
from datetime import datetime
from pathlib import Path
from calculate_metrics import MOSCOW,metric,current_slot_completion
from completion_reporting import collect as completion,choose,BASIS
from report_tomorrow import collect as collect_slots
from overnight_completion import resolve
from metric_exclusions import load,filter_slots
from enrich_slots import atomic_json
from refresh_dashboard import merge_feed
from proxy_config import configured_proxy
from courier_details import build


def run(feed,private,token,proxy,shop=7745):
    payload=merge_feed(None,json.loads(feed.read_text()));results=[]
    today=datetime.now(MOSCOW).date().isoformat()
    for row in sorted(payload['records'],key=lambda r:r['date']):
        if row['shop_id']!=shop or row['date']>today:continue
        day=row['date'];selected=None;source=None
        try:
            source=collect_slots(day,[shop],token,proxy)[0]
            if not source['available']:raise ValueError('Source unavailable')
            slots,_=resolve(source['slots'],token,proxy)
            excluded=load(private,day,shop);slots=filter_slots(slots,excluded)
            completion(day,shop,{'cluster_ids':source['cluster_ids']},slots,token,proxy,private)
            state=json.loads((private/'completion-night-state'/f'{shop}.json').read_text())
            history=[s for origin,saved in state['days'].items() if origin<day for s in saved['slots']]
            selected=filter_slots(choose(history+[s for s in slots if s['slot_type']=='limited'],day),excluded)
            value=current_slot_completion(selected);value['basis']=BASIS
            named=build(day,{'shop_id':shop,'slots':slots},{'slot_fill':metric(0,0),'planned_completion':value},completion_slots=selected)['metrics']['planned_completion']
            outcome='refreshed'
        except (RuntimeError,OSError,ValueError,KeyError,TypeError,StopIteration):
            value=metric(reason='completion_history_incomplete',basis=BASIS)
            named={'aggregate':value,'groups':[],'reconciled':False,'note':'Исторические факты для новой формулы получить не удалось.'}
            outcome='source_unavailable'
        generated=datetime.now(MOSCOW).isoformat()
        updated={**row,'reported_at':generated,'metrics':{**row.get('metrics',{}),'planned_completion':value}}
        # The existing merge preserves only same-method confirmed results on failure.
        payload=merge_feed(payload,{'schema_version':1,'records':[updated]})
        path=private/'details'/f'{day}-{shop}.json'
        detail=json.loads(path.read_text()) if path.exists() else {'kind':'courier_metric_details','schema_version':1,'date':day,'shop_id':shop,'metrics':{}}
        if detail.get('date')!=day or detail.get('shop_id')!=shop:raise ValueError('Private detail identity changed')
        detail['metrics']['planned_completion']=named;detail['generated_at']=generated;atomic_json(path,detail)
        atomic_json(feed,payload);feed.chmod(0o644)
        result={'date':day,'shop_id':shop,'status':outcome,'planned_completion':value}
        results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--feed',type=Path,default=Path('/opt/courier-analytics/current-site/data/dashboard.json'))
    args=p.parse_args()
    token=json.loads(Path('/root/curator-session.json').read_text())['token']
    if not isinstance(token,str) or not token or any(c in token for c in '\r\n'):raise SystemExit('Invalid private session')
    run(args.feed,Path('/opt/courier-analytics/private'),token,configured_proxy())
