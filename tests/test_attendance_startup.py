import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_bot import verify_startup
class Startup(unittest.TestCase):
 def setUp(self):self.config={'chat_id':-1004439978802,'bot_id':99,'human_review_required':True,'automatic_limit_changes':False}
 def test_group_rename_preserves_access_by_exact_id(self):
  with patch('attendance_bot.api',side_effect=[{'id':self.config['chat_id'],'title':'Опоздания 9107 — новое название'},{'id':99,'username':'bot'},{'url':''}]):
   self.assertEqual(verify_startup(self.config,'fixture')['id'],99)
 def test_wrong_group_or_bot_and_existing_webhook_remain_blocked(self):
  for responses in ([{'id':-9}],[{'id':self.config['chat_id']},{'id':100}],[{'id':self.config['chat_id']},{'id':99},{'url':'https://example.invalid/hook'}]):
   with patch('attendance_bot.api',side_effect=responses),self.assertRaises(ValueError):verify_startup(self.config,'fixture')
 def test_human_review_requirements_not_weakened(self):
  with self.assertRaises(ValueError):verify_startup({**self.config,'automatic_limit_changes':True},'fixture')
