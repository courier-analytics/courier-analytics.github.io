"""Read-only service inventory without credentials, environment or command args."""
import json,subprocess,sqlite3
from pathlib import Path

def inventory():
 result=subprocess.run(['systemctl','list-unit-files','--type=service','--type=timer','--no-legend','--no-pager'],capture_output=True,text=True,check=True)
 units=[]
 for line in result.stdout.splitlines():
  name=line.split()[0]
  if name.startswith(('courier-','superset-','onec-')):
   data=subprocess.run(['systemctl','show',name,'-p','Id','-p','ActiveState','-p','SubState','-p','Result','-p','FragmentPath','-p','WorkingDirectory','-p','TimeoutStartUSec','-p','MemoryMax','-p','TasksMax','-p','NRestarts'],capture_output=True,text=True,check=True).stdout
   units.append(dict(line.split('=',1) for line in data.splitlines() if '=' in line))
 return units
if __name__=='__main__':
 print(json.dumps(inventory(),ensure_ascii=False,indent=2))
