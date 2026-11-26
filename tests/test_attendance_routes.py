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

class MemberReview7745(unittest.TestCase):
 def test_7745_members_enabled_without_expanding_other_groups(self):
  from attendance_routes import reviewer_allowed
  config={'chat_id':-1004439978802,'shop_routes':{'8889':-1003908974924,'7745':-1004365044892},'member_approval_shops':[8889,7745],'approver_ids':[1]}
  current={'payload':{'shop_id':7745},'message_id':10,'message_chat_id':-1004365044892}
  routed=case_config(config,current)
  self.assertTrue(reviewer_allowed(routed,{'user':{'id':7,'is_bot':False},'status':'member'},7))
  self.assertFalse(reviewer_allowed(routed,{'user':{'id':7,'is_bot':False},'status':'left'},7))
  self.assertFalse(case_config(config,{'payload':{'shop_id':9107}})['allow_group_members'])
  self.assertFalse(case_config(config,{'payload':{'shop_id':7745},'message_id':9,'message_chat_id':-1004439978802})['allow_group_members'])
  self.assertTrue(case_config(config,{'payload':{'shop_id':8889}})['allow_group_members'])

class MemberReview9107(unittest.TestCase):
 def test_existing_9107_cards_allow_members_without_expanding_old_other_shop_cards(self):
  from enable_9107_member_approval import enabled_config,CHAT
  from attendance_routes import reviewer_allowed
  original={'chat_id':CHAT,'bot_id':99,'shop_routes':{'8889':-1003908974924,'7745':-1004365044892},'member_approval_shops':[8889,7745],'approver_ids':[1]}
  config=enabled_config(original)
  self.assertNotIn('9107',original['shop_routes'])
  self.assertEqual(config['member_approval_shops'],[7745,8889,9107])
  member={'user':{'id':7,'is_bot':False},'status':'member'}
  for bound in (None,CHAT):
   case={'payload':{'shop_id':9107},'message_id':12,'message_chat_id':bound}
   self.assertTrue(reviewer_allowed(case_config(config,case),member,7))
  for shop in (8889,7745):
   self.assertFalse(case_config(config,{'payload':{'shop_id':shop},'message_id':12,'message_chat_id':CHAT})['allow_group_members'])
  self.assertFalse(case_config(config,{'payload':{'shop_id':9107},'message_id':12,'message_chat_id':-1004365044892})['allow_group_members'])
 def test_unexpected_existing_route_is_not_replaced(self):
  from enable_9107_member_approval import enabled_config,CHAT
  with self.assertRaises(ValueError):enabled_config({'chat_id':CHAT,'shop_routes':{'9107':-999}})
