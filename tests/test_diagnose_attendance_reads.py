import sys,tempfile,sqlite3,json,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from diagnose_attendance_reads import inspect
class Diagnostic(unittest.TestCase):
 def test_read_only_output_does_not_echo_payload_secrets(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   with sqlite3.connect(root/'cases.sqlite3') as db:
    db.execute('CREATE TABLE cases(payload TEXT,state TEXT,read_attempts INT,last_read_error TEXT,result TEXT)')
    db.execute('INSERT INTO cases VALUES(?,?,?,?,?)',(json.dumps({'date':'2026-11-25','shop_id':7745,'courier_id':'123','name':'PRIVATE_NAME'}),'held',3,'PRIVATE_ERROR',None))
   (root/'worker.log').write_text('PRIVATE_NAME "stage_failed": "verify_search_results"')
   report=inspect(root)
   self.assertEqual(report['worker_tail_stages'],{'verify_search_results':1})
   self.assertNotIn('PRIVATE',json.dumps(report))
   with sqlite3.connect(root/'cases.sqlite3') as db:self.assertEqual(db.execute('SELECT count(*) FROM cases').fetchone()[0],1)
