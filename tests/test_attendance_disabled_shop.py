import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_cases import connect,ingest,get,callback_decision
from attendance_bot import notify,start_job
from attendance_shop_policy import enabled
from test_attendance_cases import evidence,CONFIG
import disable_7745_attendance as disable

class DisabledShop(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'cases.db';self.db=connect(self.path)
  p=evidence();p['shop_id']=7745;ingest(self.db,[p],[]);self.identity='a'*24
  self.config={**CONFIG,'disabled_attendance_shops':[7745]}
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def test_only_requested_shop_is_disabled(self):
  self.assertFalse(enabled(self.config,7745));self.assertTrue(enabled(self.config,8889));self.assertTrue(enabled(self.config,9107))
 def test_disabled_ready_case_sends_no_message(self):
  self.db.execute("UPDATE cases SET state='ready',current_limit=5,target_limit=4,observed=1");self.db.commit()
  with patch('attendance_bot.api') as api:notify(self.db,self.config,'token');api.assert_not_called()
 def test_disabled_shop_is_not_scheduled(self):
  with patch('attendance_bot.subprocess.Popen') as process:
   self.assertIsNone(start_job(self.db,self.config));process.assert_not_called()
 def test_old_button_cannot_approve_disabled_shop(self):
  self.db.execute("UPDATE cases SET state='pending_review',message_id=9,nonce='12345678',current_limit=5,target_limit=4,observed=1");self.db.commit()
  with self.assertRaisesRegex(ValueError,'disabled'):callback_decision(self.db,self.identity,'12345678',111,CONFIG['chat_id'],9,'apply',self.config,now=2)
 def test_disable_preserves_other_shop_and_config_and_retires_pending_case(self):
  p=evidence();p['event_id']='b'*64;p['courier_id']='456';ingest(self.db,[p],[])
  configpath=Path(self.tmp.name)/'config.json';configpath.write_text(json.dumps(CONFIG))
  with patch.object(disable,'CONFIG',configpath),patch.object(disable,'connect',side_effect=lambda:connect(self.path)):disable.disable()
  updated=json.loads(configpath.read_text());self.assertEqual(updated['approver_ids'],CONFIG['approver_ids']);self.assertEqual(updated['disabled_attendance_shops'],[7745])
  self.assertEqual(get(self.db,self.identity)['state'],'withdrawn');self.assertEqual(get(self.db,'b'*24)['state'],'need_limit')
 def test_in_progress_write_prevents_configuration_change(self):
  configpath=Path(self.tmp.name)/'config.json';original=json.dumps(CONFIG);configpath.write_text(original)
  self.db.execute("UPDATE cases SET state='applying'");self.db.commit()
  with patch.object(disable,'CONFIG',configpath),patch.object(disable,'connect',side_effect=lambda:connect(self.path)):
   with self.assertRaises(ValueError):disable.disable()
  self.assertEqual(configpath.read_text(),original);self.assertEqual(get(self.db,self.identity)['state'],'applying')
