import sys,tempfile,time,unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_cases import connect,ingest,get,callback_decision
from attendance_bot import notify,TZ
from test_attendance_cases import evidence,CONFIG

class Preliminary(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=connect(Path(self.tmp.name)/'cases.db');self.id='a'*24
  row=evidence();row['date']=datetime.now(TZ).date().isoformat();ingest(self.db,[row],[])
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def test_busy_onec_does_not_hide_case_and_ready_edits_same_message(self):
  with patch('attendance_bot.api',return_value={'message_id':99}) as api:
   notify(self.db,CONFIG,'token');notify(self.db,CONFIG,'token')
   self.assertEqual(api.call_count,1)
   self.assertIn('Лимит проверяется',api.call_args.args[2]['text'])
   self.assertEqual(api.call_args.args[2]['reply_markup'],{'inline_keyboard':[]})
   self.assertEqual(get(self.db,self.id)['state'],'need_limit')
   self.db.execute("UPDATE cases SET state='ready',current_limit=5,target_limit=4,observed=?,notified=0",(time.time(),));self.db.commit()
   notify(self.db,CONFIG,'token')
   self.assertEqual(api.call_args.args[1],'editMessageText')
   self.assertEqual(api.call_args.args[2]['message_id'],99)
   self.assertEqual(api.call_args.args[2]['reply_markup']['inline_keyboard'][0][0]['text'],'Применить')
   self.assertEqual(get(self.db,self.id)['state'],'pending_review')
   self.assertEqual(sum(c.args[1]=='sendMessage' for c in api.call_args_list),1)
 def test_unresolved_case_is_visible_without_apply(self):
  self.db.execute("UPDATE cases SET state='held',result='limit_read_failed'");self.db.commit()
  with patch('attendance_bot.api',return_value={'message_id':99}) as api:
   notify(self.db,CONFIG,'token');notify(self.db,CONFIG,'token')
   self.assertEqual(api.call_count,1)
   self.assertIn('уменьшение не выполнялось',api.call_args.args[2]['text'])
   self.assertEqual(api.call_args.args[2]['reply_markup'],{'inline_keyboard':[]})
 def test_unknown_send_is_not_repeated_or_used_for_approval(self):
  with patch('attendance_bot.api',side_effect=RuntimeError('network')) as api:
   notify(self.db,CONFIG,'token');notify(self.db,CONFIG,'token');self.assertEqual(api.call_count,1)
  case=get(self.db,self.id);self.assertEqual(case['notice_state'],'uncertain');self.assertEqual(case['state'],'need_limit')
  with self.assertRaises(ValueError):callback_decision(self.db,self.id,case['nonce'],111,CONFIG['chat_id'],99,'apply',CONFIG)
 def test_edit_failure_preserves_known_card_and_does_not_send_duplicate(self):
  with patch('attendance_bot.api',return_value={'message_id':99}):notify(self.db,CONFIG,'token')
  self.db.execute("UPDATE cases SET state='ready',current_limit=5,target_limit=4,observed=?,notified=0",(time.time(),));self.db.commit()
  with patch('attendance_bot.api',side_effect=RuntimeError('network')) as api:
   with self.assertRaises(RuntimeError):notify(self.db,CONFIG,'token')
   self.assertEqual(api.call_args.args[1],'editMessageText')
  self.assertEqual(get(self.db,self.id)['state'],'ready')
