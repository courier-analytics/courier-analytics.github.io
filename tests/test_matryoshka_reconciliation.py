import sys,sqlite3,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from reconcile_matryoshka_orders import reconcile
from collect_matryoshka_grafana import epoch
class Reconciliation(unittest.TestCase):
 def test_enrollment_boundaries_and_overlapping_counts(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'orders.db'
   with sqlite3.connect(path) as db:
    db.execute('CREATE TABLE orders(courier_id TEXT,delivered REAL)')
    db.execute('CREATE TABLE meta(key TEXT,value TEXT)')
    for cid,stamp in [('1','2026-11-19'),('1','2026-11-21'),('1','2026-11-23'),('2','2026-11-21')]:
     db.execute('INSERT INTO orders VALUES(?,?)',(cid,epoch(stamp)))
   snapshot={'verified':True,'observed_at':'2026-11-22','participants':[{'courier_id':'1','enrolled_at':'2026-11-20','enrollment_id':'m1','count_scope':'delivered_since_enrollment','delivered_orders':50}]}
   row=reconcile(path,snapshot)['participants'][0]
   self.assertEqual(row['grafana_known_at_superset_time'],1)
   self.assertEqual(row['grafana_known_newer'],1)
   self.assertEqual(row['difference'],49)
   self.assertIsNone(row['combined_total'])
   self.assertFalse(row['automatic_transition_allowed'])
