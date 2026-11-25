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
