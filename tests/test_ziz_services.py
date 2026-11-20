import sys,unittest
from pathlib import Path
from datetime import date
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from ziz_services import query,pairs
class ZizServicesTests(unittest.TestCase):
 def test_exact_shop_calendar_range_and_only_two_dimensions(self):
  q=query(date(2026,11,19),date(2026,11,20))['queries'][0]
  self.assertEqual(q['columns'],['delivery_type','name_service'])
  self.assertEqual(q['filters'],[{'col':'shopno','op':'IN','val':[9107]}])
  self.assertEqual(q['time_range'],'2026-11-19T00:00:00 : 2026-11-21T00:00:00')
 def test_unique_naturally_sorted_pairs_no_non_ziz_or_padding(self):
  rows=[{'delivery_type':z,'name_service':s,'pair_present':1} for z,s in [('ЗиЗ-11','B'),('ЗиЗ-02','A  '),('ЗиЗ-02','A'),('Такси','C')]]
  self.assertEqual(pairs(rows),[('ЗиЗ-02','A'),('ЗиЗ-11','B')])
 def test_limits_and_missing_label_fail_closed(self):
  with self.assertRaises(ValueError):pairs([{'delivery_type':'ЗиЗ-1','name_service':None,'pair_present':1}])
  with self.assertRaises(ValueError):pairs([{}]*10000)
  with self.assertRaises(ValueError):query(date(2026,11,18),date(2026,11,20))
if __name__=='__main__':unittest.main()
