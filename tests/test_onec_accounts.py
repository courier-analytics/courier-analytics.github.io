import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import onec_accounts as accounts
import configure_secondary_onec as setup

class Accounts(unittest.TestCase):
 def test_missing_configuration_preserves_primary_lock(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(accounts,'ENABLED',Path(folder)/'missing'):
   self.assertEqual(accounts.pool_account(),('primary',accounts.PRIMARY_LOCK))
 def test_same_account_is_rejected_even_with_different_case_and_spaces(self):
  with patch.object(accounts,'load_credentials',side_effect=[{'username':'User'},{'username':' user '}]):
   with self.assertRaises(ValueError):accounts.secondary_credentials()
 def test_secondary_credentials_never_overwrite_primary(self):
  with tempfile.TemporaryDirectory() as folder:
   secondary=Path(folder)/'secondary.json'
   with patch.object(setup,'SECONDARY',secondary),patch.object(setup,'load_credentials',return_value={'username':'primary'}):
    with self.assertRaises(ValueError):setup.save_secondary('Primary','secret')
    self.assertFalse(secondary.exists())
    setup.save_secondary('different','secret')
    self.assertEqual(secondary.stat().st_mode&0o777,0o600)
    self.assertEqual(json.loads(secondary.read_text())['username'],'different')
 def test_enabled_mode_uses_separate_lock_and_validates_credentials(self):
  with tempfile.TemporaryDirectory() as folder:
   mode=Path(folder)/'mode';mode.write_text('{"pool_reads":true}');mode.chmod(0o600)
   # Test workspace may run as non-root; emulate the root-owned metadata check.
   real=mode.lstat()
   from types import SimpleNamespace
   info=SimpleNamespace(st_mode=real.st_mode,st_uid=0)
   with patch.object(accounts,'ENABLED',mode),patch.object(accounts.Path,'lstat',return_value=info),patch.object(accounts,'secondary_credentials') as verify:
    self.assertEqual(accounts.pool_account(),('secondary',accounts.SECONDARY_LOCK));verify.assert_called_once()
 def test_secondary_cli_rejects_roster_and_write_modes_before_credentials(self):
  import probe_powerbi_vpn
  for flags in [['--onec-inspect-roster'],['--onec-test-decrement-zhukov','--onec-courier-shop','9107','--onec-courier-name','Жуков Максим Сергеевич']]:
   argv=['probe','--address','10.210.254.19','--onec-account','secondary','--onec-login',*flags]
   with patch.object(sys,'argv',argv),patch.object(probe_powerbi_vpn,'candidate') as candidate:
    with self.assertRaises(ValueError):probe_powerbi_vpn.main()
    candidate.assert_not_called()
