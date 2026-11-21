import sys,unittest
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
if __name__=='__main__':unittest.main()
