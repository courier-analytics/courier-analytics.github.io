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

class MemberReview(unittest.TestCase):
 def test_only_current_human_members_can_review(self):
  from attendance_routes import reviewer_allowed
  config={'allow_group_members':True,'approver_ids':[]}
  for status,allowed in [('member',True),('administrator',True),('creator',True),('left',False),('kicked',False),('restricted',False)]:
   self.assertEqual(reviewer_allowed(config,{'user':{'id':7,'is_bot':False},'status':status},7),allowed)
  self.assertFalse(reviewer_allowed(config,{'user':{'id':7,'is_bot':True},'status':'administrator'},7))
 def test_policy_only_applies_in_selected_shop_group(self):
  config={'chat_id':-1,'shop_routes':{'8889':-2},'member_approval_shops':[8889]}
  self.assertTrue(case_config(config,{'payload':{'shop_id':8889}})['allow_group_members'])
  self.assertFalse(case_config(config,{'payload':{'shop_id':8889},'message_id':9})['allow_group_members'])
  self.assertFalse(case_config(config,{'payload':{'shop_id':7745}})['allow_group_members'])

class Separate7745(unittest.TestCase):
 def test_three_destinations_and_existing_card_binding(self):
  config={'chat_id':-1004439978802,'shop_routes':{'8889':-1003908974924,'7745':-1004365044892},'member_approval_shops':[8889]}
  for shop,chat in ((8889,-1003908974924),(7745,-1004365044892),(9107,-1004439978802)):
   routed=case_config(config,{'payload':{'shop_id':shop}})
   self.assertEqual(routed['chat_id'],chat)
   self.assertEqual(routed['allow_group_members'],shop==8889)
  self.assertEqual(case_config(config,{'payload':{'shop_id':7745},'message_id':12})['chat_id'],-1004439978802)
