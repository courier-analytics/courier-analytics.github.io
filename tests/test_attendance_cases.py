import json,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_cases import connect,ingest,get,callback_decision,claim_write,proposed_target
from attendance_bot import buttons,message
CONFIG={'chat_id':-1001234567890,'approver_ids':[111,222]}
def evidence():return {'event_id':'a'*64,'date':'2026-11-22','shop_id':9107,'courier_id':'123','slot_id':9,'name':'Fixture Courier',
 'planned_start':'2026-11-22T08:00:00+03:00','actual_start':'2026-11-22T08:40:00+03:00','source_status':'Опоздал на 40 мин',
 'late_seconds':2400,'proposed_measure':{'operation':'subtract','value':1},'unresolved_facts':False,'multiple_bookings_for_courier':False}
class CaseApprovalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=connect(Path(self.tmp.name)/'test.sqlite3')
  ingest(self.db,[evidence()],[]);self.id='a'*24
  self.db.execute("UPDATE cases SET state='pending_review',current_limit=5,target_limit=4,observed=100,message_id=9,nonce='12345678' WHERE id=?",(self.id,));self.db.commit()
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def decide(self,actor=111,chat=-1001234567890,msg=9,action='apply',now=101):
  return callback_decision(self.db,self.id,'12345678',actor,chat,msg,action,CONFIG,now)
 def test_either_reviewer_can_approve_but_second_cannot_repeat(self):
  self.assertEqual(self.decide(actor=222),'approved')
  with self.assertRaises(ValueError):self.decide()
  claim_write(self.db,self.id)
  with self.assertRaises(ValueError):claim_write(self.db,self.id)
 def test_no_claim_without_individual_human_decision(self):
  with self.assertRaises(ValueError):claim_write(self.db,self.id)
 def test_group_message_and_actor_must_all_match(self):
  for values in [{'actor':77},{'chat':-100999},{'msg':10}]:
   with self.assertRaises(ValueError):self.decide(**values)
  self.assertEqual(get(self.db,self.id)['state'],'pending_review')
 def test_stale_limit_needs_new_human_review(self):
  self.assertEqual(self.decide(now=401),'refresh')
  self.assertEqual(get(self.db,self.id)['state'],'need_limit')
  with self.assertRaises(ValueError):claim_write(self.db,self.id)
 def test_skip_and_original_exception_do_not_write(self):
  self.assertEqual(self.decide(action='skip'),'skipped')
  ingest(self.db,[evidence()],[])
  self.assertEqual(get(self.db,self.id)['state'],'skipped')
  with self.assertRaises(ValueError):claim_write(self.db,self.id)
 def test_changed_facts_invalidate_approval(self):
  self.decide();changed=evidence();changed['late_seconds']=6000;changed['proposed_measure']['value']=2
  ingest(self.db,[changed],[])
  self.assertEqual(get(self.db,self.id)['state'],'need_limit')
  with self.assertRaises(ValueError):claim_write(self.db,self.id)
 def test_target_is_fixed_not_repeated_subtraction(self):
  self.assertEqual(proposed_target(5,{'operation':'subtract','value':2}),3)
  self.assertEqual(proposed_target(5,{'operation':'set','value':1}),1)
  for n in (0,1):
   with self.assertRaises(ValueError):proposed_target(n,{'operation':'subtract','value':1})
 def test_report_shows_exact_before_after_and_short_buttons(self):
  case=get(self.db,self.id);text=message(case)
  self.assertIn('Текущий лимит: 5',text);self.assertIn('Предлагаемый лимит: 4',text)
  for button in buttons(case)['inline_keyboard'][0]:self.assertLessEqual(len(button['callback_data'].encode()),64)
if __name__=='__main__':unittest.main()
