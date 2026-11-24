import sys,unittest
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_review import proposed_measure,review_rows
class AttendanceReviewTests(unittest.TestCase):
 def test_strict_thresholds(self):
  self.assertIsNone(proposed_measure('late',1800))
  self.assertEqual(proposed_measure('late',1801),{'operation':'subtract','value':1})
  self.assertEqual(proposed_measure('late',5400),{'operation':'subtract','value':1})
  self.assertEqual(proposed_measure('late',5401),{'operation':'subtract','value':2})
 def test_no_show_requires_noncontradictory_source_status(self):
  self.assertEqual(proposed_measure('no_show',None),{'operation':'set','value':1})
  self.assertIsNone(proposed_measure('no_show',None,True))
  self.assertIsNone(proposed_measure('expected',6000))
  self.assertIsNone(proposed_measure('late',None))
 def test_start_date_and_review_gate(self):
  with self.assertRaises(ValueError):review_rows({'shops':[]},'2026-11-21')
  slot={'date':'2026-11-22','slot_id':1,'slot_type':'limited','scope_kind':'shopno','scope_id':9107,'time_from':'08:00',
        'couriers':[{'courier_id':'123','name':'Fixture','shift_status':'Не вышел','shift_start':None}]}
  source={'shops':[{'shop_id':9107,'slots':[slot]}]}
  a=review_rows(source,'2026-11-22')[0];b=review_rows(source,'2026-11-22')[0]
  self.assertEqual(a['event_id'],b['event_id'])
  self.assertEqual(a['review_state'],'pending_review');self.assertFalse(a['applied'])
  self.assertIsNone(a['current_limit']);self.assertIsNone(a['target_limit'])
class NoShowDelayTests(unittest.TestCase):
 def source(self,shop,start='08:00'):
  return {'shops':[{'shop_id':shop,'slots':[{'date':'2026-11-24','slot_id':1,'slot_type':'limited','scope_kind':'shopno','scope_id':shop,'time_from':start,'couriers':[{'courier_id':'123','name':'Fixture','shift_status':'Не вышел','shift_start':None}]}]}]}
 def test_three_hour_boundary_for_each_shop(self):
  for shop in (8889,7745,9107):
   source=self.source(shop)
   self.assertEqual(review_rows(source,'2026-11-24',datetime.fromisoformat('2026-11-24T10:59:59+03:00')),[])
   rows=review_rows(source,'2026-11-24',datetime.fromisoformat('2026-11-24T11:00:00+03:00'))
   self.assertEqual(len(rows),1);self.assertEqual(rows[0]['proposed_measure'],{'operation':'set','value':1})
 def test_future_slot_and_midnight_do_not_trigger_early(self):
  self.assertEqual(review_rows(self.source(8889,'23:00'),'2026-11-24',datetime.fromisoformat('2026-11-25T01:59:59+03:00')),[])
  self.assertEqual(len(review_rows(self.source(8889,'23:00'),'2026-11-24',datetime.fromisoformat('2026-11-25T02:00:00+03:00'))),1)
if __name__=='__main__':unittest.main()
