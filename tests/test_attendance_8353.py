import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_8353 import measure,capped_target,transport_label
from attendance_cases import case_target
from attendance_shop_policy import enabled
from enable_8353_attendance import updated_config,CHAT
from attendance_review import proposed_measure,review_rows
from attendance_routes import case_config,reviewer_allowed
class Policy8353(unittest.TestCase):
 def test_exact_thresholds_and_no_inherited_no_show_penalty(self):
  self.assertIsNone(measure('late',900));self.assertIsNone(measure('no_show',7200))
  self.assertEqual(measure('late',901)['operation'],'transport_cap')
  self.assertEqual(measure('late',3600)['operation'],'transport_cap')
  self.assertEqual(measure('late',3601),{'operation':'set','value':1})
  self.assertIsNone(proposed_measure('no_show',None,False,8353))
 def test_fixed_caps_and_no_increases(self):
  self.assertEqual(capped_target(10,901,'bike'),3)
  self.assertEqual(capped_target(10,3600,'car'),8)
  self.assertEqual(capped_target(10,3601,None),1)
  for current,transport in [(3,'bike'),(2,'bike'),(8,'car'),(5,'car')]:
   with self.assertRaises(ValueError):capped_target(current,1000,transport)
 def test_unknown_transport_never_guessed(self):
  self.assertEqual(transport_label('3 - Авто'),'car');self.assertEqual(transport_label('7 - Вело'),'bike')
  self.assertEqual(transport_label('9 - Мобильный Вело Курьер'),'bike')
  for value in ('Пеший','',None,'Авто или вело'):
   with self.assertRaises(ValueError):transport_label(value)
 def test_configuration_preserves_7745_shutdown_and_other_routes(self):
  initial={'disabled_attendance_shops':[7745],'shop_routes':{'9107':-1001,'7745':CHAT},'member_approval_shops':[9107]}
  config=updated_config(initial)
  self.assertFalse(enabled(config,7745));self.assertTrue(enabled(config,8353));self.assertTrue(enabled(config,8889))
  self.assertEqual(config['shop_routes']['9107'],-1001);self.assertEqual(config['shop_routes']['8353'],CHAT)
 def test_8353_inactive_until_explicit_configuration(self):
  self.assertFalse(enabled({},8353))
 def test_group_members_can_review_only_bound_8353_cards(self):
  config=updated_config({'chat_id':-1001,'approver_ids':[111]})
  route=case_config(config,{'payload':{'shop_id':8353},'message_id':None,'message_chat_id':None})
  self.assertEqual(route['chat_id'],CHAT)
  self.assertTrue(reviewer_allowed(route,{'user':{'id':777},'status':'member'},777))
  self.assertFalse(reviewer_allowed(route,{'user':{'id':777},'status':'left'},777))
 def test_target_revalidated_against_current_transport(self):
  case={'payload':{'shop_id':8353,'late_seconds':1000},'current_limit':10,'courier_transport':'car'}
  self.assertEqual(case_target(case),8);self.assertEqual(case_target(case,10,'bike'),3)

 def test_source_rows_include_only_8353_lateness_over_threshold(self):
  slot={'date':'2026-11-28','slot_id':1,'slot_type':'limited','scope_kind':'shopno','scope_id':8353,'time_from':'08:00',
        'couriers':[{'courier_id':'123','name':'Fixture Courier','shift_status':'Опоздал','shift_start':'2026-11-28T08:16:00+03:00'}]}
  rows=review_rows({'shops':[{'shop_id':8353,'slots':[slot]}]},'2026-11-28')
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['proposed_measure']['operation'],'transport_cap')
  slot['couriers'][0]['shift_start']='2026-11-28T08:15:00+03:00'
  self.assertEqual(review_rows({'shops':[{'shop_id':8353,'slots':[slot]}]},'2026-11-28'),[])
 def test_enable_never_reactivates_7745_even_if_old_flag_missing(self):
  self.assertFalse(enabled(updated_config({}),7745))
