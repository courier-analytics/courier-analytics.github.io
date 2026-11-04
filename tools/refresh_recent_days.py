"""Refresh yesterday and today separately; keep successful dates when another source fails."""
import argparse,json
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from proxy_config import configured_proxy
from refresh_all_shops import refresh
from enrich_slots import atomic_json


def run(day,token,proxy,private,feed,active_base=False):
    results=[]
    for current in (day-timedelta(days=1),day):
        value=current.isoformat()
        try:
            report=refresh(value,token,proxy,private,feed,active_base=active_base)
            metrics=next((s['metrics'] for s in report['report']['summaries'] if s['shop_id']==7745),{})
            results.append({'date':value,'ok':True,'unavailable':{k:m['reason'] for k,m in metrics.items() if m.get('value') is None}})
        except (RuntimeError,ValueError,KeyError,TypeError,OSError) as error:
            results.append({'date':value,'ok':False,'error':type(error).__name__})
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--feed',type=Path,required=True)
    p.add_argument('--private-dir',type=Path,default=Path('/opt/courier-analytics/private'))
    p.add_argument('--session',type=Path,default=Path('/root/curator-session.json'))
    args=p.parse_args();day=datetime.now(ZoneInfo('Europe/Moscow')).date()
    token=json.loads(args.session.read_text())['token']
    if not isinstance(token,str) or not token or '\n' in token or '\r' in token:raise ValueError('Invalid session')
    args.private_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    results=run(day,token,configured_proxy(),args.private_dir,args.feed,Path('/etc/courier-analytics/active-base-enabled.json').exists())
    health={'observed_at':datetime.now(ZoneInfo('Europe/Moscow')).isoformat(),'dates':results}
    atomic_json(args.private_dir/'refresh-health.json',health)
    print(json.dumps(health,ensure_ascii=False,indent=2))
    return 0 if results[-1]['ok'] else 1


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError):raise SystemExit('Recent-days refresh failed; inspect private service status. No credentials printed.')
