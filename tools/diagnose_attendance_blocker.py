"""Read-only diagnosis of shared attendance deferrals; never stop processes or print credentials."""
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from datetime import datetime
from zoneinfo import ZoneInfo
TZ=ZoneInfo('Europe/Moscow')
ROOT=Path('/opt/courier-analytics/private/attendance-bot')
LOCKS=('/opt/courier-analytics/onec-roster.lock','/opt/courier-analytics/onec-secondary.lock','/run/lock/courier-corporate-vpn.lock','/run/lock/courier-vpn-users.lock')


def run(args):
    try:
        result=subprocess.run(args,capture_output=True,text=True,timeout=10)
        return result.returncode,result.stdout
    except (OSError,subprocess.TimeoutExpired):return -1,''


def owner(pid):
    try:
        root=Path('/proc')/str(pid)
        fields=(root/'stat').read_text().rsplit(')',1)[1].split()
        age=float(Path('/proc/uptime').read_text().split()[0])-int(fields[19])/os.sysconf('SC_CLK_TCK')
        return {'pid':pid,'process':(root/'comm').read_text().strip(),'age_seconds':round(age),'services':re.findall(r'([\w@.\-]+\.service)',(root/'cgroup').read_text())}
    except (OSError,ValueError,IndexError):return {'pid':pid,'details_unavailable':True}


def locks():
    keys={}
    for name in LOCKS:
        path=Path(name)
        if path.exists():
            info=path.stat();keys[(os.major(info.st_dev),os.minor(info.st_dev),info.st_ino)]=name
    found=[]
    for line in Path('/proc/locks').read_text().splitlines():
        if '->' in line:continue
        parts=line.split()
        if len(parts)<6:continue
        try:
            major,minor,inode=parts[5].split(':');key=(int(major,16),int(minor,16),int(inode))
            if key in keys:found.append({'path':keys[key],'mode':parts[3],'owner':owner(int(parts[4]))})
        except (ValueError,IndexError):continue
    return found


def tail(path):
    if not path.exists():return ''
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-65536));return stream.read().decode('utf-8',errors='replace')


def main():
    report={'observed_at':datetime.now(TZ).isoformat(),'locks':locks(),'services':{}}
    for unit in ('courier-attendance-bot.service','courier-corporate-vpn.service'):
        code,text=run(['systemctl','show',unit,'-p','ActiveState','-p','SubState','-p','MainPID','-p','ExecMainStatus','-p','NRestarts'])
        report['services'][unit]=dict(line.split('=',1) for line in text.splitlines() if '=' in line)
    code,route=run(['ip','-j','route','get','10.210.254.19'])
    try:report['onec_route_interfaces']=[r.get('dev') for r in json.loads(route)] if code==0 else []
    except ValueError:report['onec_route_interfaces']=[]
    path=ROOT/'worker.log';text=tail(path)
    markers=['Corporate VPN unavailable; read deferred; no tunnel stopped','Using managed corporate VPN; collector will not stop the tunnel','Temporary corporate VPN connected','Corporate VPN resource queued; waiting for current job']
    report['worker_log']={'modified_at':datetime.fromtimestamp(path.stat().st_mtime,TZ).isoformat() if path.exists() else None,'safe_recent_markers':[line for line in text.splitlines() if line in markers][-8:]}
    private=tail(Path('/var/log/courier-corporate-vpn/private.log'))
    report['vpn_private_log_signals']={key:key in private for key in ('Initialization Sequence Completed','AUTH_FAILED','TLS Error')}
    dbpath=ROOT/'cases.sqlite3'
    if dbpath.exists():
        with sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True) as db:
            report['heartbeat']=dict(db.execute("SELECT key,value FROM meta WHERE key IN ('last_loop','last_source_success','last_source_error')"))
            counts={};today=datetime.now(TZ).date().isoformat()
            for payload,state in db.execute('SELECT payload,state FROM cases'):
                p=json.loads(payload)
                if p.get('date')==today:
                    shop=str(p['shop_id']);counts.setdefault(shop,{})[state]=counts.setdefault(shop,{}).get(state,0)+1
            report['today_states_by_shop']=counts
    report['note']='No process arguments, credentials or raw VPN logs printed. Managed VPN intentionally owns the legacy VPN lock. Owner age is process age, not lock duration. No processes or case states changed.'
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
