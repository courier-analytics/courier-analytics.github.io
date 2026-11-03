"""Apply an explicit user-confirmed disabled-courier exception and recalculate one date."""
import argparse,json,subprocess,sys
from datetime import date,datetime,timezone
from pathlib import Path
from enrich_slots import atomic_json
from metric_exclusions import load


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--date',required=True);p.add_argument('--shop',required=True,type=int,choices=[7745,5818,4747,8092]);p.add_argument('--courier',required=True)
    args=p.parse_args();args.date=date.fromisoformat(args.date).isoformat()
    if not args.courier.isascii() or not args.courier.isdigit() or not 6<=len(args.courier)<=12:raise ValueError('Invalid courier identity')
    private=Path('/opt/courier-analytics/private');ids=load(private,args.date,args.shop)|{args.courier}
    folder=private/'metric-exclusions';folder.mkdir(parents=True,exist_ok=True,mode=0o700);folder.chmod(0o700)
    atomic_json(folder/f'{args.date}-{args.shop}.json',{'date':args.date,'shop_id':args.shop,'courier_ids':sorted(ids),'reason':'user_confirmed_disabled','recorded_at':datetime.now(timezone.utc).isoformat()})
    scripts=Path(__file__).resolve().parent
    python='/opt/courier-analytics/import-venv/bin/python';feed='/opt/courier-analytics/current-site/data/dashboard.json'
    # Keep the refresh lock through publication; subprocesses inherit the lock only inside this context.
    import fcntl
    with open('/opt/courier-analytics/refresh.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        subprocess.run([python,str(scripts/'refresh_all_shops.py'),'--date',args.date,'--feed',feed],check=True)
        subprocess.run(['flock','-w','120','/opt/courier-analytics/publish.lock',python,str(scripts/'publish_dashboard.py'),'--feed',feed],check=True)
    subprocess.run(['systemctl','start','courier-web-data.service'],check=True)
    row=next(r for r in json.loads(Path(feed).read_text())['records'] if r['date']==args.date and r['shop_id']==args.shop)
    print(json.dumps({'date':args.date,'shop_id':args.shop,'excluded_count':len(ids),'metrics':{k:row['metrics'][k] for k in ['planned_attendance','planned_late']}},ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError):raise SystemExit('Exclusion update did not complete; saved plan preserved. Inspect the service output.')
