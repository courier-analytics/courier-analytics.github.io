"""Collect a bounded date window with checkpoints; suitable for systemd-run."""
import argparse,fcntl,json,os,subprocess,sys,time
from datetime import date,datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from dashboard_shops import TARGETS
from enrich_slots import atomic_json
from proxy_config import configured_proxy
from refresh_all_shops import refresh


def window(first,last):
    if first>last or (last-first).days>30:raise ValueError('Use an ordered window of at most 31 days')
    return [(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)]


def run(shop,first,last,base,session,collect=refresh,publish=None,now=None):
    today=(now or datetime.now(ZoneInfo('Europe/Moscow'))).date()
    days=window(first,last)
    if shop not in TARGETS or last>today:raise ValueError('Unknown shop or future report date')
    base=Path(base);private=base/'private';private.mkdir(mode=0o700,parents=True,exist_ok=True)
    state_path=private/f'backfill-{shop}-{first}-{last}.json'
    feed=base/'current-site/data/dashboard.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {'shop_id':shop,'dates':{},'published':False}
    if state.get('shop_id')!=shop:raise ValueError('Checkpoint shop mismatch')
    token=json.loads(Path(session).read_text())['token']
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token:raise ValueError('Invalid session')
    with (base/'refresh.lock').open('a') as lock:
        deadline=time.monotonic()+180
        while True:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise RuntimeError('refresh_lock_busy')
                time.sleep(2)
        for day in days:
            # Completed historical dates can resume, but today must refresh live.
            previous=state.get('dates',{}).get(day,{})
            current=json.loads(feed.read_text()) if feed.exists() else {'records':[]}
            saved=next((r for r in current['records'] if r['shop_id']==shop and r['date']==day),None)
            if day!=today.isoformat() and previous.get('ok') and saved and saved['reported_at']==previous.get('reported_at'):
                print('Already collected:',day,flush=True);continue
            state.update(stage='collecting',current_date=day,published=False)
            atomic_json(state_path,state)
            print('Collecting:',day,'DS',shop,flush=True)
            result=collect(day,token,configured_proxy(),private,feed,
                active_base=Path('/etc/courier-analytics/active-base-enabled.json').exists())
            rows=[r for r in result['report']['summaries'] if r['shop_id']==shop and r['date']==day]
            if len(rows)!=1:raise RuntimeError('requested_shop_observation_missing')
            stored=json.loads(feed.read_text())
            matches=[r for r in stored['records'] if r['shop_id']==shop and r['date']==day]
            if len(matches)!=1:raise RuntimeError('requested_shop_not_saved')
            record=matches[0]
            state['dates'][day]={'ok':True,'reported_at':record['reported_at'],'metrics':record.get('metrics',{})}
            atomic_json(state_path,state)
            print(json.dumps({'shop_id':shop,'date':day,**state['dates'][day]},ensure_ascii=False),flush=True)
        state['stage']='publishing';atomic_json(state_path,state)
        if publish is None:
            subprocess.run(['flock','-w','120',str(base/'publish.lock'),sys.executable,
                str(Path(__file__).with_name('publish_dashboard.py')),'--feed',str(feed)],check=True)
        else:publish(feed)
        state.update(stage='complete',published=True,completed_at=datetime.now(ZoneInfo('Europe/Moscow')).isoformat())
        atomic_json(state_path,state)
    if publish is None and Path('/opt/courier-dashboard/app/app.py').exists():
        subprocess.run(['systemctl','start','courier-web-data.service'],check=True)
    print('Published DS',shop,first,'through',last,flush=True)
    return state


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--shop',type=int,required=True)
    p.add_argument('--from',dest='first',type=date.fromisoformat,required=True)
    p.add_argument('--to',dest='last',type=date.fromisoformat,required=True)
    p.add_argument('--base',type=Path,default=Path('/opt/courier-analytics'))
    p.add_argument('--session',type=Path,default=Path('/root/curator-session.json'))
    args=p.parse_args();os.umask(0o077)
    try:run(args.shop,args.first,args.last,args.base,args.session)
    except Exception as error:
        raise SystemExit('Backfill failed: '+type(error).__name__+'. Completed dates remain checkpointed; no session data printed.')
