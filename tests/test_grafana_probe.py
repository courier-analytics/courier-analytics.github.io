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
  document={'dashboard':{'panels':[{'id':6,'targets':[{'datasource':{'type':'postgres'},'rawSql':'SELECT * FROM courier WHERE courier_id IN (${courier_id:csv})'}]}], 'templating':{'list':[{'name':'courier_id','query':'SELECT courier_id FROM parcel WHERE shop_number IN (${shop_number:csv})'}]}}}
  sql=shop_query(document,9107)['rawSql']
  self.assertIn('shop_number IN (9107)',sql)
  self.assertNotIn('$',sql)
  self.assertIn('${courier_id:csv}',document['dashboard']['panels'][0]['targets'][0]['rawSql'])
  with self.assertRaises(ValueError):shop_query(document,'9107')
  document['dashboard']['panels'][0]['targets'][0]['rawSql']+='; DELETE FROM courier'
  with self.assertRaises(ValueError):shop_query(document,9107)
