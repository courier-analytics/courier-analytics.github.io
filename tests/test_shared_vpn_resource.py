import sys,tempfile,unittest,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from shared_vpn_resource import acquire
class Isolation(unittest.TestCase):
 def test_second_process_cannot_enter_until_first_releases(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'lease';first=acquire(path,0)
   script="import sys;sys.path.insert(0,sys.argv[1]);from shared_vpn_resource import acquire;lease=acquire(sys.argv[2],0)"
   args=[sys.executable,'-c',script,str(Path(__file__).resolve().parents[1]/'tools'),str(path)]
   denied=subprocess.run(args,capture_output=True)
   self.assertNotEqual(denied.returncode,0);self.assertIn(b'queue wait expired',denied.stderr)
   first.close();self.assertEqual(subprocess.run(args,capture_output=True).returncode,0)
if __name__=='__main__':unittest.main()
