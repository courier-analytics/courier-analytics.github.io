"""Repair one aggregate from matching saved slot evidence; no API or 1C calls."""
import copy
import fcntl
import json
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from calculate_metrics import calculate
from build_dashboard_feed import validate_metrics
from typed_roster_8889 import load_for_day
from metric_exclusions import load,views
from enrich_slots import atomic_json
from prepare_openvpn import private_write

ROOT=Path('/opt/courier-analytics/private')

def repair(feed,observations,roster,day,excluded):
    if observations.get('date')!=day:raise ValueError('Saved slot evidence is for another date')
    scope=[s for s in observations.get('scope_config',{}).get('shops',[]) if s['shop_id']==8889 and s.get('scope_verified') is True]
    shops=[s for s in observations['shops'] if s['shop_id']==8889]
    records=[r for r in feed['records'] if r['shop_id']==8889 and r['date']==day]
    if len(scope)!=1 or len(shops)!=1 or len(records)!=1:raise ValueError('Exact DS8889 source/record missing')
    slots,_,roster=views(shops[0]['slots'],None,roster,excluded)
    metrics=calculate(slots,day,roster=roster)
    fill=metrics['slot_fill'];record=records[0]
    if (fill['numerator'],fill['denominator'])!=(record['booked_places'],record['capacity']):raise ValueError('Slot evidence differs from published feed')
    result=copy.deepcopy(feed)
    target=next(r for r in result['records'] if r['shop_id']==8889 and r['date']==day)
    target['metrics']['shift_marked']=metrics['shift_marked']
    validate_metrics(target['metrics'])
    return result,shops[0],roster

def main():
    with Path('/opt/courier-analytics/refresh.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Refresh is running; no changes made. Retry after it finishes.')
        day=datetime.now(ZoneInfo('Europe/Moscow')).date().isoformat()
        roster=load_for_day(ROOT/'onec-rosters',day)
        observations=json.loads((ROOT/'all-shops/all-shops-observations.json').read_text())
        source=Path('/opt/courier-analytics/current-site/data/dashboard.json')
        settings=json.loads(Path('/etc/courier-dashboard/settings.json').read_text())
        destinations={source.resolve(),(Path(settings['data_root'])/'dashboard.json').resolve()}
        prepared=[]
        excluded=load(ROOT,day,8889)
        for path in destinations:
            feed=json.loads(path.read_text())
            updated,shop,selected=repair(feed,observations,roster,day,excluded)
            prepared.append((path,updated))
        backup=ROOT/('8889-metric-repair-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
        backup.mkdir(mode=0o700)
        for index,(path,updated) in enumerate(prepared):private_write(backup/f'feed-{index}.json',path.read_text())
        # Reconcile the named detail for the changed aggregate only.
        from courier_details import build
        row=next(r for r in prepared[0][1]['records'] if r['shop_id']==8889 and r['date']==day)
        detail_path=ROOT/'details'/f'{day}-8889.json'
        detail=json.loads(detail_path.read_text())
        adjusted_slots,_,_=views(shop['slots'],None,roster,excluded)
        group=build(day,{**shop,'slots':adjusted_slots},row['metrics'],selected)['metrics']['shift_marked']
        if not group['reconciled']:raise ValueError('Named metric details did not reconcile')
        private_write(backup/'details.json',detail_path.read_text())
        detail['metrics']['shift_marked']=group
        atomic_json(detail_path,detail)
        for path,updated in prepared:
            atomic_json(path,updated);path.chmod(0o644)
        print('DS8889 first metric repaired:',json.dumps(row['metrics']['shift_marked'],ensure_ascii=False),flush=True)
        print('Original evidence retained; unrelated metrics unchanged.',flush=True)
if __name__=='__main__':main()
