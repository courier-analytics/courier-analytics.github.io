import json,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_cases import connect,ingest,get,callback_decision,claim_write,proposed_target
from attendance_bot import buttons,message,finish_job
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
class WorkerFailureTests(CaseApprovalTests):
 def test_failed_read_yields_queue_then_stops_after_three_attempts(self):
  other=evidence();other['event_id']='b'*64;other['courier_id']='456'
  ingest(self.db,[other],[])
  for attempt in (1,2,3):
   self.db.execute("UPDATE cases SET state='reading',read_attempts=? WHERE id=?",(attempt,self.id));self.db.commit()
   finish_job(self.db,(None,self.id,'read',0))
   case=get(self.db,self.id)
   if attempt<3:
    self.assertEqual(case['state'],'need_limit')
    self.assertGreater(case['next_attempt'],time.time())
    queued=self.db.execute("SELECT id FROM cases WHERE state='need_limit' AND next_attempt<=?",(time.time(),)).fetchall()
    self.assertEqual([r['id'] for r in queued],['b'*24])
   else:
    self.assertEqual(case['state'],'held');self.assertEqual(case['result'],'limit_read_failed')
 def test_busy_shared_connection_does_not_exhaust_read_attempts(self):
  from types import SimpleNamespace
  self.db.execute("UPDATE cases SET state='reading',read_attempts=3 WHERE id=?",(self.id,));self.db.commit()
  finish_job(self.db,(SimpleNamespace(returncode=75),self.id,'read',0))
  case=get(self.db,self.id)
  self.assertEqual(case['state'],'need_limit');self.assertEqual(case['read_attempts'],2)
  self.assertGreater(case['next_attempt'],time.time())
 def test_failed_apply_never_queues_another_write(self):
  self.db.execute("UPDATE cases SET state='applying' WHERE id=?",(self.id,));self.db.commit()
  finish_job(self.db,(None,self.id,'apply',0))
  self.assertEqual(get(self.db,self.id)['state'],'uncertain')
  with self.assertRaises(ValueError):claim_write(self.db,self.id)
if __name__=='__main__':unittest.main()
