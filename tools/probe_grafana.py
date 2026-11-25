"""One Grafana login attempt and read-only dashboard inspection; secrets stay local."""
import json,os,stat,http.cookiejar,urllib.request,urllib.error,ssl,socket,subprocess
from pathlib import Path
from prepare_openvpn import private_write
BASE='https://grafana-courier.vkusvill.ru'
UID='cf2807ef-d4cf-4ac9-9def-c8c8630c1d32'
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def panels(dashboard):
 for panel in dashboard.get('panels',[]):
  yield panel
  yield from panels(panel)

class GrafanaNetworkError(RuntimeError):pass

def network_reason(error):
 reason=error.reason if isinstance(error,urllib.error.URLError) else error
 if isinstance(reason,ssl.SSLCertVerificationError):return 'tls_certificate_verification_failed'
 if isinstance(reason,ssl.SSLError):return 'tls_handshake_failed'
 if isinstance(reason,socket.gaierror):return 'dns_resolution_failed'
 if isinstance(reason,(TimeoutError,socket.timeout)):return 'connection_timed_out'
 if isinstance(reason,ConnectionRefusedError):return 'connection_refused'
 if isinstance(reason,OSError):return 'network_os_error_'+str(reason.errno)
 return 'network_connection_failed'

def network_check():
 try:
  addresses=sorted({r[4][0] for r in socket.getaddrinfo('grafana-courier.vkusvill.ru',443,type=socket.SOCK_STREAM)})
  print('Grafana DNS:',json.dumps(addresses),flush=True)
 except OSError as error:print('Grafana DNS:',network_reason(error),flush=True)
 result=subprocess.run(['curl','--silent','--show-error','--connect-timeout','10','--max-time','20',
     '--output','/dev/null','--write-out','%{http_code}',BASE+'/api/health'],capture_output=True,text=True,timeout=25)
 print('Grafana unauthenticated HTTPS:',json.dumps({'curl_exit':result.returncode,'http_status':result.stdout.strip()[:3]}),flush=True)

def probe(credentials=Path('/root/courier-grafana.json'),folder=Path('/opt/courier-analytics/private/grafana')):
 info=credentials.lstat()
 if not stat.S_ISREG(info.st_mode) or info.st_mode&0o077 or info.st_uid!=os.geteuid():raise ValueError('Credential file owner/permissions invalid')
 saved=json.loads(credentials.read_text())
 if not all(isinstance(saved.get(k),str) and saved[k] for k in ('username','password')):raise ValueError('Missing credentials')
 jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar),NoRedirect())
 def request(path,data=None):
  if path not in ('/login','/api/user','/api/dashboards/uid/'+UID):raise ValueError('Endpoint not allowed')
  headers={'Accept':'application/json','Origin':BASE,'Referer':BASE+'/login'}
  body=None if data is None else json.dumps(data).encode()
  if body is not None:headers['Content-Type']='application/json'
  req=urllib.request.Request(BASE+path,data=body,headers=headers)
  try:
   with opener.open(req,timeout=25) as response:
    raw=response.read(4_000_001)
    if len(raw)>4_000_000:raise ValueError('Response exceeds inspection bound')
    try:answer=json.loads(raw)
    except ValueError:answer=None
    return response.status,answer
  except urllib.error.HTTPError as error:return error.code,None
  except (urllib.error.URLError,TimeoutError,ssl.SSLError) as error:raise GrafanaNetworkError(network_reason(error)) from None
 code,_=request('/login',{'user':saved['username'],'password':saved['password']})
 print('Grafana login HTTP:',code,flush=True)
 code,user=request('/api/user')
 authenticated=code==200 and isinstance(user,dict) and isinstance(user.get('id'),int)
 print('Grafana authenticated session:',authenticated,'HTTP:',code,flush=True)
 if not authenticated:return False
 code,document=request('/api/dashboards/uid/'+UID)
 print('Dashboard read HTTP:',code,flush=True)
 if code!=200 or not isinstance(document,dict) or document.get('dashboard',{}).get('uid')!=UID:return False
 found=[p for p in panels(document['dashboard']) if p.get('id')==6]
 if len(found)!=1:raise ValueError('Panel 6 not uniquely present')
 panel=found[0];folder.mkdir(mode=0o700,parents=True,exist_ok=True)
 # Dashboard query definitions only. No cookies, saved credentials or order rows.
 private_write(folder/'dashboard-definition.json',json.dumps(document,ensure_ascii=False,indent=2))
 summary={'panel_id':6,'panel_type':panel.get('type'),'target_count':len(panel.get('targets',[])),
  'datasource_types':sorted({str(t.get('datasource',{}).get('type')) for t in panel.get('targets',[]) if isinstance(t.get('datasource'),dict)}),
  'refresh':document['dashboard'].get('refresh'),'order_data_queried':False}
 print('Panel inspection:',json.dumps(summary,ensure_ascii=False),flush=True)
 print('Private dashboard definition saved; no orders or secrets printed.',flush=True)
 return True
if __name__=='__main__':
 os.umask(0o077)
 try:
  network_check()
  raise SystemExit(0 if probe() else 1)
 except GrafanaNetworkError as error:
  print('Grafana connection failure:',str(error),flush=True)
  raise SystemExit(1)
 except (ValueError,KeyError,OSError,RuntimeError) as error:
  print('Grafana check failed:',type(error).__name__,'; private details hidden',flush=True)
  raise SystemExit(1)
