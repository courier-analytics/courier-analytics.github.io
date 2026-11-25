import sys,sqlite3,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from merge_matryoshka_history import merge
from collect_matryoshka_grafana import epoch
class Merge(unittest.TestCase):
 def test_exact_id_union_preserves_raw_and_is_idempotent(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'orders.db';raw=epoch('2026-11-20T15:00:00Z')
   with sqlite3.connect(path) as db:
    db.execute('CREATE TABLE orders(order_id TEXT PRIMARY KEY,courier_id TEXT,delivered REAL)')
    db.execute('INSERT INTO orders VALUES(?,?,?)',('1','123',raw))
   snapshot={'verified':True,'participants':[{'courier_id':'123','enrolled_at':'2026-11-20T20:00:00+03:00'}]}
   comparison={'participants':[{'courier_id':'123','superset_rows':[{'id_order':i,'id_courier':'123','delivered_at':'2026-11-20 21:00:00'} for i in ('1','2')]}]}
   for _ in range(2):
    row=merge(path,comparison,snapshot)['participants'][0]
    self.assertEqual(row['confirmed_superset_unique_orders'],2)
    self.assertEqual(row['also_in_grafana'],1)
   with sqlite3.connect(path) as db:self.assertEqual(db.execute('SELECT delivered FROM orders').fetchone()[0],raw)
