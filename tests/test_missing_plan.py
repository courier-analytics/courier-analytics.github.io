import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from diagnose_missing_plan import differences,redact,slot_history_path
class MissingPlanTests(unittest.TestCase):
 def test_manual_and_limited_use_evidenced_generic_history_endpoint(self):
  self.assertEqual(slot_history_path(42,'manual'),'/v1/schedules/slots/42/history?slot_type=manual')
  self.assertEqual(slot_history_path(1,'limited'),'/v1/schedules/slots/1/history?slot_type=limited')
  with self.assertRaises(ValueError):slot_history_path('../secret','manual')
  with self.assertRaises(ValueError):slot_history_path(1,'unknown')
 def test_moved_booking_is_reported_as_missing_original_with_other_facts(self):
  original={'slot_id':1,'slot_type':'limited','time_from':'07:00','time_to':'19:00','couriers':[{'courier_id':'111111'},{'courier_id':'222222'}]}
  current=[{**original,'couriers':[{'courier_id':'222222'}]},{**original,'slot_id':2,'couriers':[{'courier_id':'111111','shift_start':'2026-11-03T07:18:00+03:00'}]}]
  missing=differences([original],current)
  self.assertEqual(len(missing),1);self.assertEqual(missing[0]['courier_id'],'111111')
  self.assertEqual(missing[0]['other_current_bookings'][0]['slot']['slot_id'],2)
 def test_no_missing_is_not_replaced_with_no_show_and_sensitive_fields_are_removed(self):
  slot={'slot_id':1,'slot_type':'limited','time_from':'07:00','time_to':'19:00','couriers':[{'courier_id':'111111'}]}
  self.assertEqual(differences([slot],[slot]),[])
  self.assertEqual(redact({'events':[{'courier_id':'111111','access_token':'SECRET','password':'SECRET'}]}),{'events':[{'courier_id':'111111'}]})
