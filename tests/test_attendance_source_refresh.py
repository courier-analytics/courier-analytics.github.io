import sys,unittest,sqlite3
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_source_refresh import run_once
class SourceRefresh(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
 def tearDown(self):self.db.close()
 def test_success_clears_old_error_and_records_success(self):
  self.db.execute("INSERT INTO meta VALUES('last_source_error','old_error')");self.db.commit()
  collect=Mock()
  self.assertEqual(run_once(self.db,{'fixture':True},collect),0)
  collect.assert_called_once_with(self.db,{'fixture':True})
  metadata=dict(self.db.execute('SELECT * FROM meta'))
  self.assertIn('last_source_success',metadata);self.assertNotIn('last_source_error',metadata)
 def test_failure_preserves_previous_success(self):
  self.db.execute("INSERT INTO meta VALUES('last_source_success','previous')");self.db.commit()
  self.assertEqual(run_once(self.db,{},Mock(side_effect=RuntimeError('PRIVATE_RESPONSE'))),1)
  metadata=dict(self.db.execute('SELECT * FROM meta'))
  self.assertEqual(metadata['last_source_success'],'previous')
  self.assertNotIn('PRIVATE_RESPONSE',metadata['last_source_error'])
