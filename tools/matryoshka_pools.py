"""Private, read-only 1C pool snapshots keyed by verified courier identity."""
import json,subprocess,sys,fcntl
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from prepare_openvpn import private_write
ROOT=Path('/opt/courier-analytics/private')
CACHE=ROOT/'matryoshka-pools.json'
TZ=ZoneInfo('Europe/Moscow')
def save_read(page,identity,name):
 from onec_limit_test import card
 _,limit,_=card(page,identity,name)
 with (ROOT/'matryoshka-pools-cache.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  data=json.loads(CACHE.read_text()) if CACHE.exists() else {}
  data[identity]={'limit':limit,'verified':True,'observed_at':datetime.now(TZ).isoformat()}
  private_write(CACHE,json.dumps(data,ensure_ascii=False))

def label(identity,now,pools):
 if not isinstance(pools,dict):pools={}
 row=pools.get(identity,{})
 if not isinstance(row,dict):row={}
 try:
  observed=datetime.fromisoformat(row['observed_at']);value=row['limit']
  if row.get('verified') is not True or type(value) is not int or value<0 or observed.tzinfo is None or observed>now+timedelta(minutes=2):raise ValueError()
 except (KeyError,TypeError,ValueError):return 'Пул: нет подтверждённых данных 1С'
 return f'Пул: {value} · проверен в 1С {observed.astimezone(TZ):%d.%m %H:%M} МСК'
def main():
 snapshot=json.loads((ROOT/'matryoshka-monitor.json').read_text())
 if snapshot.get('verified') is not True:raise ValueError('Unverified participants')
 from matryoshka_command_report import membership
 roster=Path('/opt/courier-contacts/connected/all.json')
 groups=membership(json.loads(roster.read_text()) if roster.exists() else {})
 from onec_accounts import pool_account
 account,account_lock=pool_account()
 seen=set()
 for p in snapshot['participants']:
  identity=p['courier_id'];name=p.get('name');shops=groups.get(identity,set());last=str(p.get('last_shop',''))
  shop=next(iter(shops)) if len(shops)==1 else last if last in ('8889','7745','9107') and (not shops or last in shops) else None
  if identity in seen:continue
  seen.add(identity)
  if not identity.isdigit() or not name or shop not in ('8889','7745','9107'):continue
  result=subprocess.run(['flock','-w','0','-E','75',str(account_lock),'/opt/courier-analytics/onec-venv/bin/python','/opt/courier-analytics/dashboard-code/tools/probe_powerbi_vpn.py','--address','10.210.254.19','--onec-account',account,'--onec-login','--onec-courier-shop',shop,'--onec-courier-name',name,'--onec-pool-id',identity],timeout=330)
  if result.returncode==75:
   print('Pool collection deferred: shared resource busy; remaining participants wait for next timer',flush=True)
   return 75
  print('Pool read completed; success:',result.returncode==0,flush=True)
if __name__=='__main__':raise SystemExit(main())
