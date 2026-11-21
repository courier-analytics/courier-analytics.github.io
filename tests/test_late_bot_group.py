import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from late_bot_group import chat_from_link,verified_config
class LateGroupTests(unittest.TestCase):
 def test_private_message_and_topic_links(self):
  for link in ['https://t.me/c/1234567890/12','https://t.me/c/1234567890/5/12']:
   self.assertEqual(chat_from_link(link),-1001234567890)
  for link in ['https://evil.example/c/123/4','https://t.me/+invite','https://t.me/c/123/4?x=1']:
   with self.assertRaises(ValueError):chat_from_link(link)
 def test_verified_group_and_human_review_guard(self):
  chat={'id':-100123,'type':'supergroup','title':'Опоздавшие'};bot={'id':1};member={'user':{'id':1},'status':'administrator'}
  value=verified_config(chat,bot,member,[2,2])
  self.assertEqual(value['approver_ids'],[2]);self.assertTrue(value['human_review_required']);self.assertFalse(value['automatic_limit_changes'])
  for bad_chat,bad_member,ids in [({**chat,'title':'Тест'},member,[2]),(chat,{**member,'status':'member'},[2]),(chat,member,[])]:
   with self.assertRaises(ValueError):verified_config(bad_chat,bot,bad_member,ids)
if __name__=='__main__':unittest.main()
