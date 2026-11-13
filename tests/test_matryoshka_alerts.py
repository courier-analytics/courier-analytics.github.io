import sys,unittest
from pathlib import Path
from datetime import datetime,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from matryoshka_alerts import stage,plan
NOW=datetime.fromisoformat('2026-11-13T12:00:00+03:00')
def snapshot(count=100,current=24):
 return {'verified':True,'observed_at':NOW.isoformat(),'participants':[{'courier_id':'111111','enrollment_id':'pilot-A','name':'TEST','enrolled_at':'2026-11-01T00:00:00+03:00','count_scope':'delivered_since_enrollment','current_type_verified':True,'current_type':current,'delivered_orders':count}]}
class MatryoshkaTests(unittest.TestCase):
 def test_boundaries(self):
  for n,s in [(0,1),(99,1),(100,2),(299,2),(300,3),(599,3),(600,4),(999,4),(1000,None),(1001,None)]:self.assertEqual(stage(n),s)
  for n in [-1,True,1.5,'100']:
   with self.assertRaises(ValueError):stage(n)
 def test_transport_and_skipped_stages(self):
  self.assertEqual(plan(snapshot(305,24),NOW)['alerts'][0]['to_type'],26)
  self.assertEqual(plan(snapshot(600,28),NOW)['alerts'][0]['to_type'],31)
 def test_no_change_and_no_downgrade(self):
  self.assertFalse(plan(snapshot(299,25),NOW)['alerts'])
  self.assertEqual(plan(snapshot(99,25),NOW)['blocked'][0]['reason'],'count_below_current_stage_no_automatic_downgrade')
 def test_acknowledged_notice_does_not_repeat_as_count_grows(self):
  event=plan(snapshot(100),NOW)['alerts'][0]['event_id']
  self.assertFalse(plan(snapshot(250),NOW,[event])['alerts'])
  self.assertTrue(plan(snapshot(300),NOW,[event])['alerts'])
 def test_old_snapshot_cannot_trigger_notice(self):
  with self.assertRaises(ValueError):plan(snapshot(),NOW+timedelta(minutes=6))
 def test_unknown_current_type_and_incomplete_count_are_blocked(self):
  self.assertFalse(plan(snapshot(100,3),NOW)['alerts'])
  s=snapshot();s['participants'][0]['count_scope']='current_type_only'
  self.assertFalse(plan(s,NOW)['alerts'])
 def test_no_assumed_type_after_program(self):
  result=plan(snapshot(1000,27),NOW)['alerts'][0]
  self.assertEqual(result['kind'],'completed');self.assertIsNone(result['to_type'])
  self.assertFalse(plan(snapshot(1001,27),NOW,[result['event_id']])['alerts'])
