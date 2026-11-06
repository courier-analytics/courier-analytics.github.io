import contextlib,importlib.util,io,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import check_dashboard_access as access

class DashboardAccessTests(unittest.TestCase):
 def run_check(self,args,login=True):
  result={'status':'HTTP/1.1 200 OK' if login else 'HTTP/1.1 503 Unavailable','login_available':login}
  with patch.object(sys,'argv',['check_dashboard_access.py']+args),patch.object(access,'HOST','courier-7745.147.90.10.158.sslip.io'),patch.object(access,'IP','147.90.10.158'),patch.object(access,'dns',return_value={}),patch.object(access,'tcp',return_value={}),patch.object(access,'http',return_value=result),patch('socket.gethostbyname',return_value='8.8.4.4') as dns,contextlib.redirect_stdout(io.StringIO()) as output:
   access.main();host,ip=access.HOST,access.IP
  return host,ip,output.getvalue(),dns.call_count
 def test_new_assigned_ip_and_hostname_can_be_checked_without_default_origin(self):
  host,ip,output,count=self.run_check(['--host','courier-7745.8.8.8.8.nip.io','--ip','8.8.8.8'])
  self.assertEqual((host,ip),('courier-7745.8.8.8.8.nip.io','8.8.8.8'));self.assertEqual(count,0)
  self.assertIn('8.8.8.8',output)
 def test_new_host_can_resolve_its_own_ip_and_failed_app_is_not_reported_ready(self):
  host,ip,output,count=self.run_check(['--host','dashboard.example.ru'],login=False)
  self.assertEqual(ip,'8.8.4.4');self.assertEqual(count,1)
  self.assertIn('503',output);self.assertIn('HTTPS-соединение установлено',output)
 def test_invalid_host_and_private_ip_are_rejected_before_probes(self):
  for args in (['--host','https://example.ru/login'],['--host','example.ru\r\nInjected: value'],['--ip','127.0.0.1']):
   with self.subTest(args=args),patch.object(sys,'argv',['check_dashboard_access.py']+args),patch.object(access,'tcp') as tcp,contextlib.redirect_stderr(io.StringIO()):
    with self.assertRaises(SystemExit):access.main()
    tcp.assert_not_called()
 def test_secondary_ip_guard_only_accepts_an_address_already_assigned_to_vps(self):
  script=(Path(__file__).resolve().parents[1]/'tools/enable_dashboard_alternate_address.sh').read_text()
  block=script.split("<<'PY'\n",1)[1].split('\nPY',1)[0]
  import json
  interfaces=json.dumps([{'addr_info':[{'local':'147.90.10.158'},{'local':'8.8.8.8'}]}])
  with patch.object(sys,'argv',['guard','8.8.8.8']),patch('subprocess.check_output',return_value=interfaces):
   exec(compile(block,'<secondary-ip-guard>','exec'),{})
  for address in ('127.0.0.1','8.8.4.4'):
   with self.subTest(address=address),patch.object(sys,'argv',['guard',address]),patch('subprocess.check_output',return_value=interfaces):
    with self.assertRaises(SystemExit):exec(compile(block,'<secondary-ip-guard>','exec'),{})
