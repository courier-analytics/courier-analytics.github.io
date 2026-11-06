import sys,unittest
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from diagnose_blocked_metrics import completion_blockers
from calculate_metrics import MOSCOW,current_slot_completion

class CompletionBlockerTests(unittest.TestCase):
 def test_calendar_lower_bound_can_prove_day_completion_but_is_not_final_night_end(self):
  slot={'date':'2026-11-03','time_from':'20:00','time_to':'08:00','slot_id':1,'slot_type':'limited',
        'couriers':[{'courier_id':'111111','shift_status':'Вышел','shift_start':'2026-11-03T20:00:00+03:00','shift_end':'2026-11-03T23:59:59+03:00'}]}
  now=datetime(2026,11,4,12,tzinfo=MOSCOW)
  self.assertEqual(completion_blockers([slot],now)[0]['reason'],'calendar_boundary_end_unconfirmed')
  slot['time_to']='23:00'
  self.assertEqual(completion_blockers([slot],now),[])
  slot['couriers'][0].update(shift_end=None,shift_end_lower_bound='2026-11-03T23:59:59+03:00')
  self.assertEqual(completion_blockers([slot],now),[])
 def test_blocker_names_missing_end_and_does_not_guess_completion(self):
  slot={'date':'2026-11-03','time_from':'08:00','time_to':'20:00','slot_id':1,'slot_type':'limited',
        'couriers':[{'courier_id':'111111','shift_status':'Вышел','shift_start':'2026-11-03T08:00:00+03:00','shift_end':None}]}
  now=datetime(2026,11,4,12,tzinfo=MOSCOW)
  self.assertIsNone(current_slot_completion([slot],now)['value'])
  self.assertEqual(completion_blockers([slot],now)[0]['reason'],'actual_end_missing')
  slot['couriers'][0]['shift_end']='2026-11-03T20:00:00+03:00'
  self.assertEqual(completion_blockers([slot],now),[])
  self.assertEqual(current_slot_completion([slot],now)['value'],100)
