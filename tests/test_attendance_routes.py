import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_routes import case_config
class Routes(unittest.TestCase):
 def test_new_proposals_split_by_shop(self):
  config={'chat_id':-1004439978802,'shop_routes':{'8889':-1003908974924},'approver_ids':[1]}
  for shop,chat in ((8889,-1003908974924),(7745,-1004439978802),(9107,-1004439978802)):
   self.assertEqual(case_config(config,{'payload':{'shop_id':shop}})['chat_id'],chat)
  self.assertEqual(config['chat_id'],-1004439978802)
 def test_existing_callbacks_and_outcomes_keep_original_destination(self):
  config={'chat_id':-1004439978802,'shop_routes':{'8889':-1003908974924}}
  self.assertEqual(case_config(config,{'payload':{'shop_id':8889},'message_id':7})['chat_id'],-1004439978802)
  self.assertEqual(case_config(config,{'payload':{'shop_id':8889},'message_id':7,'message_chat_id':-1003908974924})['chat_id'],-1003908974924)
if __name__=='__main__':unittest.main()
