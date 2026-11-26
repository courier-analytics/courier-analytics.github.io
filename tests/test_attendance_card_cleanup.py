import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_cases import connect,ingest,get
from attendance_card_cleanup import cleanup_withdrawn
from test_attendance_cases import evidence,CONFIG

class Cleanup(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.db=connect(Path(self.tmp.name)/'cases.db');self.id='a'*24
  ingest(self.db,[evidence()],[])
  self.db.execute("UPDATE cases SET state='withdrawn',message_id=9,message_chat_id=-100888,notified=1");self.db.commit()
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def test_deletes_in_bound_group_once_and_preserves_history(self):
  api=Mock(return_value=True)
  cleanup_withdrawn(self.db,CONFIG,'token',api,now=10)
  api.assert_called_once_with('token','deleteMessage',{'chat_id':-100888,'message_id':9})
  case=get(self.db,self.id);self.assertEqual(case['state'],'withdrawn');self.assertEqual(case['cleanup_state'],'deleted');self.assertEqual(case['message_id'],9)
  cleanup_withdrawn(self.db,CONFIG,'token',api,now=1000);self.assertEqual(api.call_count,1)
 def test_deletion_rejected_closes_without_sending_new_card(self):
  api=Mock(side_effect=[RuntimeError('denied'),{'message_id':9}])
  cleanup_withdrawn(self.db,CONFIG,'token',api,now=10)
  self.assertEqual(get(self.db,self.id)['cleanup_state'],'closed')
  self.assertEqual(api.call_args.args[1],'editMessageText')
  self.assertEqual(api.call_args.args[2]['reply_markup'],{'inline_keyboard':[]})
 def test_failed_cleanup_backoff_and_no_send(self):
  api=Mock(side_effect=RuntimeError('network'))
  cleanup_withdrawn(self.db,CONFIG,'token',api,now=10)
  cleanup_withdrawn(self.db,CONFIG,'token',api,now=11)
  self.assertEqual(api.call_count,3)
  self.assertEqual(get(self.db,self.id)['cleanup_attempts'],1)
  self.assertTrue(all(call.args[1]!='sendMessage' for call in api.call_args_list))
 def test_processed_live_and_uncertain_cases_are_never_deleted(self):
  for state in ['pending_review','approved','applying','applied','skipped','uncertain','delivery_uncertain','held','ready']:
   self.db.execute('UPDATE cases SET state=?',(state,));self.db.commit()
   api=Mock();cleanup_withdrawn(self.db,CONFIG,'token',api,now=10);api.assert_not_called()
