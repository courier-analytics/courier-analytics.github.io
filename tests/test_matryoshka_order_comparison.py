import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from matryoshka_order_comparison import compare_ids
class Comparison(unittest.TestCase):
 def test_order_sets_and_unverified_namespace(self):
  report=compare_ids([{'id_order':1},{'id_order':1},{'id_order':2}],['2','3'])
  self.assertEqual(report['matching_ids'],1)
  self.assertEqual(report['only_superset'],['1'])
  self.assertEqual(report['only_grafana'],['3'])
  self.assertFalse(report['identity_namespace_verified'])
