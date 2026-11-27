import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from contextlib import ExitStack
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import corporate_vpn_session as vpn
from shared_vpn_resource import VPNBusy
from install_managed_corporate_vpn import profile_for_service

TEMP_DIRECTORY=tempfile.TemporaryDirectory

class ManagedVPN(unittest.TestCase):
 def test_service_profile_has_only_host_routes_no_dns_or_default(self):
  source='client\ndev tun\nproto tcp-client\nremote example.invalid 443\nauth-user-pass\nredirect-gateway def1\ndhcp-option DNS 10.1.1.1\nroute 10.0.0.0 255.0.0.0\npersist-tun\n'
  config,auth=profile_for_service(source,['10.210.254.19','10.0.112.18'],Path('/root/auth'))
  self.assertTrue(auth);self.assertIn('dev tun42\n',config);self.assertIn('route-nopull',config)
  self.assertNotIn('redirect-gateway',config);self.assertNotIn('dhcp-option',config);self.assertNotIn('persist-tun',config)
  self.assertEqual(sum(line.startswith('route ') for line in config.splitlines()),2)
 def test_shared_clients_enter_concurrently_without_starting_or_stopping_processes(self):
  with tempfile.TemporaryDirectory() as folder:
   marker=Path(folder)/'mode';marker.write_text('{}');users=Path(folder)/'users'
   data={'interface':'tun42','addresses':['10.210.254.19']}
   with patch.object(vpn,'SETTINGS',marker),patch.object(vpn,'USERS',users),patch.object(vpn,'settings',return_value=data),patch.object(vpn,'ready',return_value=True),patch.object(vpn,'acquire') as acquire,patch.object(vpn.subprocess,'Popen') as popen,patch.object(vpn.tempfile,'TemporaryDirectory',side_effect=lambda **kw:TEMP_DIRECTORY(dir=folder)):
    # Keep both borrowed sessions open at the same time.
    with ExitStack() as stack:
     stack.enter_context(vpn.session('unused',['10.210.254.19']))
     stack.enter_context(vpn.session('unused',['10.210.254.19']))
    acquire.assert_not_called();popen.assert_not_called()
 def test_unavailable_managed_vpn_never_falls_back_to_second_tunnel(self):
  with tempfile.TemporaryDirectory() as folder:
   marker=Path(folder)/'mode';marker.touch()
   with patch.object(vpn,'SETTINGS',marker),patch.object(vpn,'USERS',Path(folder)/'users'),patch.object(vpn,'settings',return_value={'addresses':['10.210.254.19']}),patch.object(vpn,'ready',return_value=False),patch.object(vpn,'acquire') as acquire,patch.object(vpn.subprocess,'Popen') as popen:
    with self.assertRaises(VPNBusy):
     with vpn.session('unused',['10.210.254.19']):pass
    acquire.assert_not_called();popen.assert_not_called()
 def test_wrong_destination_is_rejected_before_network_work(self):
  with tempfile.TemporaryDirectory() as folder:
   marker=Path(folder)/'mode';marker.touch()
   with patch.object(vpn,'SETTINGS',marker),patch.object(vpn,'USERS',Path(folder)/'users'),patch.object(vpn,'settings',return_value={'addresses':['10.210.254.19']}),patch.object(vpn,'ready') as ready:
    with self.assertRaises(ValueError):
     with vpn.session('unused',['10.0.112.18']):pass
    ready.assert_not_called()
 def test_route_must_use_managed_interface(self):
  for interface,expected in [('tun42',True),('eth0',False),('tun0',False)]:
   with patch.object(vpn.subprocess,'run',side_effect=[Mock(returncode=0),Mock(returncode=0,stdout=json.dumps([{'dev':interface}]))]):
    self.assertEqual(vpn.ready(['10.210.254.19'],{'interface':'tun42'}),expected)
 def test_legacy_session_still_releases_only_its_own_tunnel_and_lock(self):
  with TEMP_DIRECTORY() as folder:
   missing=Path(folder)/'missing';lease=Mock();worker=Mock();worker.poll.return_value=None
   with patch.object(vpn,'SETTINGS',missing),patch.object(vpn,'acquire',return_value=lease),patch.object(vpn.subprocess,'run',return_value=Mock(returncode=1)),patch.object(vpn.subprocess,'Popen',return_value=worker),patch.object(vpn.tempfile,'TemporaryDirectory',side_effect=lambda **kw:TEMP_DIRECTORY(dir=folder)),patch.object(vpn.Path,'read_text',return_value='Initialization Sequence Completed'):
    with vpn.session('client\ndev tun\n',['10.210.254.19']):pass
    worker.terminate.assert_called_once();worker.wait.assert_called_once();lease.close.assert_called_once()
 def test_client_failure_never_stops_managed_tunnel(self):
  with TEMP_DIRECTORY() as folder:
   marker=Path(folder)/'mode';marker.touch()
   with patch.object(vpn,'SETTINGS',marker),patch.object(vpn,'USERS',Path(folder)/'users'),patch.object(vpn,'settings',return_value={'addresses':['10.210.254.19']}),patch.object(vpn,'ready',return_value=True),patch.object(vpn.subprocess,'Popen') as popen,patch.object(vpn.tempfile,'TemporaryDirectory',side_effect=lambda **kw:TEMP_DIRECTORY(dir=folder)):
    with self.assertRaises(RuntimeError):
     with vpn.session('unused',['10.210.254.19']):raise RuntimeError('collector failed')
    popen.assert_not_called()
