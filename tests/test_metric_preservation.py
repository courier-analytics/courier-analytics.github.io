import sys,copy,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from refresh_dashboard import merge_feed
class LastGoodMetricTests(unittest.TestCase):
 def row(self):
  return {'date':'2026-11-03','shop_id':7745,'booked_places':1,'capacity':2,'fill_percent':50,'source':'slots_export',
   'reported_at':'2026-11-03T10:00:00Z','metrics':{'planned_attendance':{'value':80,'numerator':8,'denominator':10,'reason':None,'basis':'frozen_plan_unique_couriers'}}}
 def test_missing_update_keeps_last_value_with_original_timestamp_and_cause(self):
  previous={'schema_version':1,'records':[self.row()]};fresh=copy.deepcopy(previous)
  fresh['records'][0]['reported_at']='2026-11-03T11:00:00Z'
  fresh['records'][0]['metrics']['planned_attendance']={'value':None,'numerator':None,'denominator':None,'reason':'planned_booking_missing_from_current_data','basis':None}
  result=merge_feed(previous,fresh);m=result['records'][0]['metrics']['planned_attendance']
  self.assertEqual(m['value'],80);self.assertEqual(m['last_success_at'],'2026-11-03T10:00:00Z');self.assertEqual(m['stale_reason'],'planned_booking_missing_from_current_data')
  again=merge_feed(result,fresh);self.assertEqual(again['records'][0]['metrics']['planned_attendance']['last_success_at'],m['last_success_at'])
  recovered=merge_feed(again,previous)['records'][0]['metrics']['planned_attendance'];self.assertNotIn('stale_reason',recovered)
 def test_newer_valid_zero_replaces_previous_and_different_dates_do_not_inherit(self):
  old={'schema_version':1,'records':[self.row()]};new=copy.deepcopy(old);m=new['records'][0]['metrics']['planned_attendance'];m.update(value=0,numerator=0)
  self.assertEqual(merge_feed(old,new)['records'][0]['metrics']['planned_attendance']['value'],0)
  new['records'][0]['date']='2026-11-04';m.update(value=None,numerator=None,denominator=None,reason='frozen_plan_missing')
  result=merge_feed(old,new);self.assertIsNone(result['records'][1]['metrics']['planned_attendance']['value'])
