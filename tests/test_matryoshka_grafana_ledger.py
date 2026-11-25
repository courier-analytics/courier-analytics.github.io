import sys,json,tempfile,unittest,sqlite3
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from collect_matryoshka_grafana import ingest,epoch
class Ledger(unittest.TestCase):
 def test_dedup_restart_and_conflict_rollback(self):
  snapshot={'verified':True,'participants':[{'courier_id':'123','enrollment_id':'m1','enrolled_at':'2026-11-20 10:00:00'}]}
  export={'scope':'matryoshka participants across all shops','observed_at_ms':1795600000000,'rows':[{'courier_id':'123','order_id':'1','shop_number':9107,'delivered_at':'2026-11-21T10:00:00+03:00'}]}
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'orders.db'
   self.assertEqual(ingest(path,snapshot,export)['new_orders'],1)
   self.assertEqual(ingest(path,snapshot,export)['new_orders'],0)
   export['rows'][0]['shop_number']=8889
   with self.assertRaises(ValueError):ingest(path,snapshot,export)
   with sqlite3.connect(path) as db:self.assertEqual(db.execute('SELECT shop FROM orders').fetchone()[0],'9107')
 def test_moscow_naive_timestamp(self):
  self.assertEqual(epoch('2026-11-21 10:00:00'),epoch('2026-11-21T07:00:00Z'))
