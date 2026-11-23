import sys,unittest
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from matryoshka_command_report import render
class Grouping(unittest.TestCase):
 def test_warehouse_pages_keep_identity_counts_and_numbering(self):
  now=datetime.fromisoformat('2026-11-23T15:00:00+03:00')
  people=[{'courier_id':str(i),'name':'Courier '+str(i),'count_scope':'delivered_since_enrollment','current_type_verified':True,'current_type':24,'delivered_orders':i,'last_shop':shop} for i,shop in [(1,9107),(2,7745),(3,9107)]]
  snapshot={'verified':True,'observed_at':now.isoformat(),'participants':people}
  pages=render(snapshot,'',now)
  self.assertEqual(len(pages),2)
  self.assertIn('ДС 7745 · курьеров: 1',pages[0]);self.assertNotIn('Courier 1',pages[0])
  self.assertIn('ДС 9107 · курьеров: 2',pages[1]);self.assertIn('1. Courier 1',pages[1]);self.assertIn('2. Courier 3',pages[1])
  self.assertTrue(all(len(p)<3500 for p in pages))
if __name__=='__main__':unittest.main()
