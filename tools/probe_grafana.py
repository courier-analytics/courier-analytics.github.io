"""One Grafana login attempt and read-only dashboard inspection; secrets stay local."""
import re,time,json,os,stat,http.cookiejar,urllib.request,urllib.error,ssl,socket,subprocess,tempfile,argparse
from urllib.parse import urlsplit
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

def proxy_options(proxy):
 if not proxy:return ['--noproxy','*']
 value=urlsplit(proxy)
 if value.scheme not in ('socks5h','http','https') or not value.hostname or value.username or value.password or value.query or value.fragment:
  raise ValueError('Proxy must not contain credentials')
 return ['--proxy',proxy,'--noproxy','']

def network_check(proxy=None):
 try:
  addresses=sorted({r[4][0] for r in socket.getaddrinfo('grafana-courier.vkusvill.ru',443,type=socket.SOCK_STREAM)})
  print('Grafana DNS:',json.dumps(addresses),flush=True)
 except OSError as error:print('Grafana DNS:',network_reason(error),flush=True)
 command=['curl','--disable','--silent','--show-error','--connect-timeout','10','--max-time','20',
     '--output','/dev/null','--write-out','%{http_code}']+proxy_options(proxy)+[BASE+'/api/health']
 result=subprocess.run(command,capture_output=True,text=True,timeout=25)
 print('Grafana unauthenticated HTTPS:',json.dumps({'route':'proxy' if proxy else 'direct','curl_exit':result.returncode,'http_status':result.stdout.strip()[:3]}),flush=True)
 return result.returncode==0

def shop_query(document,shop):
 if type(shop) is not int or not 1 <= shop <= 999999:raise ValueError('Invalid shop')
 dashboard=document['dashboard']
 panel=next(p for p in panels(dashboard) if p.get('id')==6)
 targets=[t for t in panel.get('targets',[]) if not t.get('hide')]
 if len(targets)!=1:raise ValueError('Expected one panel query')
 target=dict(targets[0])
 variable=next(v for v in dashboard.get('templating',{}).get('list',[]) if v.get('name')=='courier_id')
 selection=variable.get('query')
 if not isinstance(selection,str):raise ValueError('Expected SQL variable')
 selection=selection.replace('${shop_number:csv}',str(shop)).strip().rstrip(';')
 sql=target.get('rawSql','').replace('${courier_id:csv}',selection).strip()
 if sql.endswith(';'):sql=sql[:-1].rstrip()
 for statement in (selection,sql):
  if not statement.lstrip().upper().startswith('SELECT') or '$' in statement or ';' in statement:
   raise ValueError('Unexpected SQL template')
  if re.search(r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|COPY|CALL|GRANT)\b',statement,re.I):
   raise ValueError('Expected read-only query')
 if target.get('datasource',{}).get('type')!='postgres':raise ValueError('Unexpected datasource')
 target.update(rawSql=sql,refId='A',format='table',rawQuery=True)
 return target

def delivered_query(document,shop,courier_ids):
 target=shop_query(document,shop)
 if not courier_ids or len(courier_ids)>100:raise ValueError('Expected 1 to 100 courier IDs')
 ids=[]
 for value in courier_ids:
  value=str(value)
  if not re.fullmatch(r'[0-9]{1,18}',value):raise ValueError('Invalid courier ID')
  ids.append(str(int(value)))
 target['rawSql']="""SELECT DISTINCT t.courier_id::text AS courier_id,
 p.parcel_id::text AS order_id, p.shop_number AS shop_number,
 t.delivered_at AS delivered_at
 FROM task t JOIN job j ON j.job_id=t.job_id
 JOIN parcel p ON p.parcel_id=j.parcel_id
 WHERE t.status='delivered' AND t.delivered_at IS NOT NULL
 AND t.delivered_at >= NOW() - INTERVAL '7 days' AND t.delivered_at < NOW()
 AND t.courier_id IN ("""+','.join(sorted(set(ids)))+""")
 ORDER BY delivered_at, courier_id, order_id LIMIT 10001"""
 return target

def frame_rows(result):
 answer=result.get('results',{}).get('A',{})
 if not answer or answer.get('error') or answer.get('status',200)!=200:
  raise ValueError('Datasource query failed')
 frames=answer.get('frames')
 if not isinstance(frames,list):raise ValueError('Missing frames')
 rows=[]
 for frame in frames:
  fields=frame.get('schema',{}).get('fields',[])
  values=frame.get('data',{}).get('values',[])
  names=[f.get('name') for f in fields]
  if len(names)!=len(set(names)) or len(names)!=len(values) or len({len(v) for v in values})>1:
   raise ValueError('Invalid frame')
  rows.extend(dict(zip(names,row)) for row in zip(*values))
 return rows

def fetch_delivered(request,target,now,page_size=5000,max_pages=100):
 # Fixed window and deterministic ordering across pages; no partial success.
 base=target['rawSql'].replace("NOW()",'to_timestamp('+str(now/1000)+')')
 suffix='ORDER BY delivered_at, courier_id, order_id LIMIT 10001'
 if not base.endswith(suffix):raise ValueError('Unexpected pagination query')
 base=base[:-len(suffix)]
 rows=[]
 for page in range(max_pages):
  query=dict(target)
  query['rawSql']=base+'ORDER BY delivered_at, courier_id, order_id, shop_number LIMIT '+str(page_size)+' OFFSET '+str(page*page_size)
  code,result=request('/api/ds/query',{'queries':[query],'from':str(now-7*86400000),'to':str(now)})
  print('Delivered page:',page+1,'HTTP:',code,flush=True)
  if code!=200 or not isinstance(result,dict):raise ValueError('Datasource query failed')
  batch=frame_rows(result)
  rows.extend(batch)
  if len(batch)<page_size:return rows
 raise ValueError('Result limit reached; incomplete export rejected')

def probe(credentials=Path('/root/courier-grafana.json'),folder=Path('/opt/courier-analytics/private/grafana'),proxy=None,query_shop=None,delivered=False,courier_ids=None):
 info=credentials.lstat()
 if not stat.S_ISREG(info.st_mode) or info.st_mode&0o077 or info.st_uid!=os.geteuid():raise ValueError('Credential file owner/permissions invalid')
 saved=json.loads(credentials.read_text())
 if not all(isinstance(saved.get(k),str) and saved[k] for k in ('username','password')):raise ValueError('Missing credentials')
 folder.mkdir(mode=0o700,parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='.login-',dir=folder) as session:
  cookies=Path(session)/'cookies.txt';private_write(cookies,'')
  def request(path,data=None):
   if path not in ('/login','/api/user','/api/dashboards/uid/'+UID,'/api/ds/query'):raise ValueError('Endpoint not allowed')
   command=['curl','--disable','--silent','--show-error','--connect-timeout','10','--max-time','25','--max-filesize','4000000',
     '--cookie',str(cookies),'--cookie-jar',str(cookies),'--header','Accept: application/json',
     '--header','Origin: '+BASE,'--header','Referer: '+BASE+'/login','--write-out','\\n%{http_code}']+proxy_options(proxy)
   body=None
   if data is not None:
    command+=['--header','Content-Type: application/json','--data-binary','@-'];body=json.dumps(data)
   response=subprocess.run(command+[BASE+path],input=body,capture_output=True,text=True,timeout=30)
   if response.returncode:
    raise GrafanaNetworkError({28:'connection_timed_out',60:'tls_certificate_verification_failed',5:'proxy_dns_failed',6:'dns_resolution_failed',7:'connection_failed',97:'proxy_connection_failed'}.get(response.returncode,'curl_error_'+str(response.returncode)))
   raw,separator,status=response.stdout.rpartition('\n')
   if not separator or not status.isdigit():raise ValueError('Malformed HTTP response')
   try:answer=json.loads(raw)
   except ValueError:answer=None
   return int(status),answer
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
  if query_shop is not None:
   target=shop_query(document,query_shop)
   now=int(time.time()*1000)
   code,result=request('/api/ds/query',{'queries':[target],'from':str(now-86400000),'to':str(now)})
   print('Orders query HTTP:',code,flush=True)
   if code!=200 or not isinstance(result,dict):return False
   answers=result.get('results',{})
   answer=answers.get('A',{})
   if not answer or answer.get('error') or answer.get('status',200)!=200:
    print('Orders query failed; private response details hidden.',flush=True);return False
   frames=answer.get('frames')
   if not isinstance(frames,list):raise ValueError('Missing data frames')
   private_write(folder/('orders-shop-'+str(query_shop)+'.json'),json.dumps(result,ensure_ascii=False))
   summary=[]
   for frame in frames:
    fields=frame.get('schema',{}).get('fields',[])
    values=frame.get('data',{}).get('values',[])
    if len(fields)!=len(values) or len({len(v) for v in values})>1:raise ValueError('Invalid frame')
    summary.append({'columns':[f.get('name') for f in fields],'rows':len(values[0]) if values else 0})
   print('Orders read:',json.dumps({'shop':query_shop,'frames':summary,'scope':'couriers_with_deliveries_from_shop; panel totals may include other shops'},ensure_ascii=False),flush=True)
  if delivered:
   if query_shop is None:raise ValueError('Shop required')
   ids=courier_ids
   if not ids:
    previous=json.loads((folder/('orders-shop-'+str(query_shop)+'.json')).read_text())
    ids=sorted({str(row['courier_id']) for row in frame_rows(previous)})
   target=delivered_query(document,query_shop,ids)
   now=int(time.time()*1000)
   rows=fetch_delivered(request,target,now)
   print('Delivered validation:',json.dumps({'rows':len(rows),'columns':sorted({k for r in rows for k in r})}),flush=True)
   required={'courier_id','order_id','shop_number','delivered_at'}
   for row in rows:
    if set(row)!=required or any(row[k] is None for k in required):raise ValueError('Incomplete order row')
    if str(row['courier_id']) not in {str(int(v)) for v in ids}:raise ValueError('Unexpected courier')
   private_write(folder/('delivered-shop-'+str(query_shop)+'.json'),json.dumps({'observed_at_ms':now,'lookback_days':7,'scope':'selected couriers across all shops','rows':rows},ensure_ascii=False))
   print('Delivered orders:',json.dumps({'requested_couriers':len(set(ids)),'rows':len(rows),'unique_order_ids':len({r['order_id'] for r in rows}),'other_shop_rows':sum(str(r['shop_number'])!=str(query_shop) for r in rows),'saved_privately':True}),flush=True)
  return True
if __name__=='__main__':
 os.umask(0o077)
 parser=argparse.ArgumentParser();parser.add_argument('--proxy');parser.add_argument('--query-shop',type=int);parser.add_argument('--delivered-orders',action='store_true');parser.add_argument('--courier-id',action='append');args=parser.parse_args()
 try:
  if not network_check(args.proxy):raise SystemExit(1)
  raise SystemExit(0 if probe(proxy=args.proxy,query_shop=args.query_shop,delivered=args.delivered_orders,courier_ids=args.courier_id) else 1)
 except GrafanaNetworkError as error:
  print('Grafana connection failure:',str(error),flush=True)
  raise SystemExit(1)
 except (ValueError,KeyError,OSError,RuntimeError) as error:
  reasons={'Result limit reached; incomplete export rejected':'result_limit_reached','Incomplete order row':'incomplete_order_row','Unexpected courier':'unexpected_courier','Invalid frame':'invalid_frame','Missing frames':'missing_frames','Datasource query failed':'datasource_query_failed'}
  print('Grafana check failed:',type(error).__name__,'reason:',reasons.get(str(error),'private_details_hidden'),flush=True)
  raise SystemExit(1)
