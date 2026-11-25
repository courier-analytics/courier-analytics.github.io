import sys,unittest,ssl,socket,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from probe_grafana import network_reason,panels
class GrafanaProbe(unittest.TestCase):
 def test_network_diagnostic_does_not_echo_exception_or_credentials(self):
  for reason,expected in ((ssl.SSLCertVerificationError('secret'),'tls_certificate_verification_failed'),(socket.gaierror('secret'),'dns_resolution_failed'),(TimeoutError('secret'),'connection_timed_out'),(ConnectionRefusedError('secret'),'connection_refused')):
   self.assertEqual(network_reason(urllib.error.URLError(reason)),expected)
  self.assertNotIn('secret',network_reason(urllib.error.URLError('secret')))
 def test_nested_panel_lookup(self):
  self.assertEqual([p['id'] for p in panels({'panels':[{'id':1,'panels':[{'id':6}]}]})],[1,6])
if __name__=='__main__':unittest.main()

class ProxyLogin(unittest.TestCase):
 def test_login_uses_proxy_and_keeps_password_out_of_arguments(self):
  import json,tempfile
  from unittest.mock import patch
  from types import SimpleNamespace
  from probe_grafana import probe,UID
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);credentials=root/'credentials.json';credentials.write_text(json.dumps({'username':'fixture','password':'PRIVATE_PASSWORD'}));credentials.chmod(0o600)
   results=[SimpleNamespace(returncode=0,stdout='{}\n200'),SimpleNamespace(returncode=0,stdout='{"id":7}\n200'),SimpleNamespace(returncode=0,stdout=json.dumps({'dashboard':{'uid':UID,'panels':[{'id':6,'type':'table','targets':[]}]}})+'\n200')]
   with patch('probe_grafana.subprocess.run',side_effect=results) as run,patch('builtins.print'):
    self.assertTrue(probe(credentials,root/'private',proxy='socks5h://127.0.0.1:18081'))
   for call in run.call_args_list:
    self.assertNotIn('PRIVATE_PASSWORD',' '.join(call.args[0]))
    self.assertIn('--proxy',call.args[0]);self.assertNotIn('--insecure',call.args[0])
   self.assertIn('PRIVATE_PASSWORD',run.call_args_list[0].kwargs['input'])
   self.assertEqual(list((root/'private').glob('.login-*')),[])

class ShopQuery(unittest.TestCase):
 def test_shop_scope_and_unresolved_variables(self):
  from probe_grafana import shop_query
  document={'dashboard':{'panels':[{'id':6,'targets':[{'datasource':{'type':'postgres'},'rawSql':'SELECT * FROM courier WHERE courier_id IN (${courier_id:csv});'}]}], 'templating':{'list':[{'name':'courier_id','query':'SELECT courier_id FROM parcel WHERE shop_number IN (${shop_number:csv})'}]}}}
  sql=shop_query(document,9107)['rawSql']
  self.assertIn('shop_number IN (9107)',sql)
  self.assertNotIn('$',sql)
  self.assertNotIn(';',sql)
  self.assertIn('${courier_id:csv}',document['dashboard']['panels'][0]['targets'][0]['rawSql'])
  with self.assertRaises(ValueError):shop_query(document,'9107')
  document['dashboard']['panels'][0]['targets'][0]['rawSql']+='; DELETE FROM courier'
  with self.assertRaises(ValueError):shop_query(document,9107)

class DeliveredOrders(unittest.TestCase):
 def test_exact_courier_ids_and_delivered_filter(self):
  from unittest.mock import patch
  from probe_grafana import delivered_query
  with patch('probe_grafana.shop_query',return_value={'datasource':{'type':'postgres'}}):
   sql=delivered_query({},9107,['123','456','123'])['rawSql']
   self.assertIn('IN (123,456)',sql)
   self.assertIn("t.status='delivered'",sql)
   self.assertIn('p.parcel_id::text AS order_id',sql)
   self.assertIn("INTERVAL '7 days'",sql)
   self.assertNotIn('p.shop_number=9107',sql)
   for ids in ([],['123); DELETE FROM task'],list(range(101))):
    with self.assertRaises(ValueError):delivered_query({},9107,ids)
 def test_frames_reject_errors_and_misaligned_columns(self):
  from probe_grafana import frame_rows
  valid={'results':{'A':{'frames':[{'schema':{'fields':[{'name':'order_id'},{'name':'courier_id'}]},'data':{'values':[['99'],['123']]}}]}}}
  self.assertEqual(frame_rows(valid),[{'order_id':'99','courier_id':'123'}])
  valid['results']['A']['frames'][0]['data']['values'][0].append('100')
  with self.assertRaises(ValueError):frame_rows(valid)
  with self.assertRaises(ValueError):frame_rows({'results':{'A':{'error':'private SQL error'}}})

class DeliveredPagination(unittest.TestCase):
 def test_multiple_pages_and_fixed_window(self):
  from unittest.mock import Mock,patch
  from probe_grafana import fetch_delivered
  target={'rawSql':"SELECT NOW() ORDER BY delivered_at, courier_id, order_id LIMIT 10001"}
  request=Mock(return_value=(200,{}))
  with patch('probe_grafana.frame_rows',side_effect=[[{'order_id':'1'},{'order_id':'2'}],[{'order_id':'3'}]]):
   rows=fetch_delivered(request,target,100000,page_size=2)
  self.assertEqual(len(rows),3)
  queries=[c.args[1]['queries'][0]['rawSql'] for c in request.call_args_list]
  self.assertIn('OFFSET 0',queries[0]);self.assertIn('OFFSET 2',queries[1])
  self.assertTrue(all('to_timestamp(100.0)' in q for q in queries))
 def test_incomplete_export_is_not_accepted(self):
  from unittest.mock import Mock,patch
  from probe_grafana import fetch_delivered
  target={'rawSql':'SELECT 1 ORDER BY delivered_at, courier_id, order_id LIMIT 10001'}
  with patch('probe_grafana.frame_rows',return_value=[{'order_id':'1'}]):
   with self.assertRaises(ValueError):fetch_delivered(Mock(return_value=(200,{})),target,100000,page_size=1,max_pages=2)

class MatryoshkaSelection(unittest.TestCase):
 def test_only_verified_participant_ids(self):
  import tempfile,json
  from probe_grafana import matryoshka_ids
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'participants.json'
   path.write_text(json.dumps({'verified':True,'participants':[{'courier_id':'123'},{'courier_id':'456'},{'courier_id':'123'}]}))
   self.assertEqual(matryoshka_ids(path),['123','456'])
   for snapshot in ({'verified':False,'participants':[{'courier_id':'123'}]},{'verified':True,'participants':[]},{'verified':True,'participants':[{'courier_id':'invalid'}]}):
    path.write_text(json.dumps(snapshot))
    with self.assertRaises(ValueError):matryoshka_ids(path)

class HistoricalWindow(unittest.TestCase):
 def test_requested_window_reaches_sql_and_api(self):
  from unittest.mock import Mock,patch
  from probe_grafana import fetch_delivered
  target={'rawSql':"SELECT NOW() - INTERVAL '7 days' ORDER BY delivered_at, courier_id, order_id LIMIT 10001"}
  request=Mock(return_value=(200,{}))
  with patch('probe_grafana.frame_rows',return_value=[]):fetch_delivered(request,target,1800000000000,lookback_days=30)
  body=request.call_args.args[1]
  self.assertIn("INTERVAL '30 days'",body['queries'][0]['rawSql'])
  self.assertEqual(body['from'],str(1800000000000-30*86400000))
