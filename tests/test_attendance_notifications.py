import sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_cases import connect,ingest,get
from attendance_bot import notify
from test_attendance_cases import evidence,CONFIG
class Notifications(unittest.TestCase):
 def test_failure_is_not_sent_as_new_card_and_ready_sends_once(self):
  with tempfile.TemporaryDirectory() as directory:
   db=connect(Path(directory)/'cases.db');ingest(db,[evidence()],[]);identity='a'*24
   db.execute("UPDATE cases SET state='held',result='limit_read_failed',notified=0 WHERE id=?",(identity,));db.commit()
   with patch('attendance_bot.api',return_value={'message_id':99}) as api:
    notify(db,CONFIG,'test');api.assert_not_called()
    db.execute("UPDATE cases SET state='ready',current_limit=8,target_limit=7,observed=? WHERE id=?",(time.time(),identity));db.commit()
    notify(db,CONFIG,'test');notify(db,CONFIG,'test')
    self.assertEqual(api.call_count,1);self.assertEqual(api.call_args.args[1],'sendMessage')
    self.assertEqual(get(db,identity)['state'],'pending_review')
   db.close()
 def test_uncertain_write_updates_existing_card_without_success_claim(self):
  with tempfile.TemporaryDirectory() as directory:
   db=connect(Path(directory)/'cases.db');ingest(db,[evidence()],[])
   db.execute("UPDATE cases SET state='uncertain',message_id=99,notified=0");db.commit()
   with patch('attendance_bot.api') as api:
    notify(db,CONFIG,'test')
    self.assertEqual(api.call_args.args[1],'editMessageText')
    self.assertIn('Результат сохранения не подтверждён',api.call_args.args[2]['text'])
    self.assertNotIn('Сохранено в 1С и проверено',api.call_args.args[2]['text'])
   db.close()
if __name__=='__main__':unittest.main()

class ReissuedRouting(unittest.TestCase):
 def test_reissued_8889_card_uses_new_group_not_old_message_binding(self):
  with tempfile.TemporaryDirectory() as directory:
   db=connect(Path(directory)/'cases.db');row=evidence();row['shop_id']=8889;ingest(db,[row],[])
   db.execute("UPDATE cases SET state='ready',current_limit=8,target_limit=6,observed=?,message_id=7,message_chat_id=?",(time.time(),CONFIG['chat_id']));db.commit()
   config={**CONFIG,'shop_routes':{'8889':-1003908974924}}
   with patch('attendance_bot.api',return_value={'message_id':99}) as api:
    notify(db,config,'test')
    sends=[call for call in api.call_args_list if call.args[1]=='sendMessage']
    self.assertEqual(len(sends),1);self.assertEqual(sends[0].args[2]['chat_id'],-1003908974924)
    self.assertEqual(get(db,'a'*24)['message_chat_id'],-1003908974924)
   db.close()
