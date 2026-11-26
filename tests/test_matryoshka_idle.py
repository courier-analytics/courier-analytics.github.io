import sys,unittest
from pathlib import Path
from datetime import datetime,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from matryoshka_command_report import render,command
class Idle(unittest.TestCase):
 def setUp(self):
  self.now=datetime.fromisoformat('2026-11-26T12:00:00+03:00')
 def person(self,identity,last):
  return {'courier_id':identity,'name':'Courier '+identity,'count_scope':'delivered_since_enrollment','current_type_verified':True,'current_type':24,'delivered_orders':10,'last_shop':9107,'last_delivery':last}
 def report(self,people):
  return '\n'.join(render({'verified':True,'observed_at':self.now.isoformat(),'participants':people},'',self.now,idle_days=3))
 def test_bad_row_does_not_hide_valid_idle_courier(self):
  text=self.report([self.person('1',(self.now-timedelta(days=3)).isoformat()),self.person('2',(self.now+timedelta(hours=3)).isoformat())])
  self.assertIn('Courier 1',text);self.assertNotIn('Courier 2',text)
  self.assertIn('Не включены в проверку простоя: 1',text)
 def test_future_only_is_not_reported_as_idle(self):
  text=self.report([self.person('2',(self.now+timedelta(hours=3)).isoformat())])
  self.assertIn('Подтверждённых участников',text)
  self.assertIn('Не включены в проверку простоя: 1',text)
  self.assertNotIn('Courier 2',text)
 def test_three_full_days_boundary_and_missing_time(self):
  text=self.report([self.person('1',(self.now-timedelta(days=3)).isoformat()),self.person('2',(self.now-timedelta(days=3)+timedelta(seconds=1)).isoformat()),self.person('3',None)])
  self.assertIn('Courier 1',text);self.assertNotIn('Courier 2',text);self.assertNotIn('Courier 3',text)
  self.assertIn('Не включены в проверку простоя: 1',text)
 def test_addressed_command_still_accepted(self):
  self.assertEqual(command('/matreshka_idle@vv_services_reports_bot','vv_services_reports_bot'),'')
