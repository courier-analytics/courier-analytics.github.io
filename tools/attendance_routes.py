"""Route each proposal and its outcome to the same bound Telegram group."""
def case_config(config,case):
    bound=case.get('message_chat_id')
    if bound is None:
        bound=config['chat_id'] if case.get('message_id') else config.get('shop_routes',{}).get(str(case['payload']['shop_id']),config['chat_id'])
    allow=case['payload']['shop_id'] in config.get('member_approval_shops',[]) and bound==config.get('shop_routes',{}).get(str(case['payload']['shop_id']))
    return {**config,'chat_id':bound,'allow_group_members':allow}

def reviewer_allowed(config,member,actor):
    user=member.get('user',{})
    if user.get('id')!=actor or user.get('is_bot'):return False
    if config.get('allow_group_members'):
        return member.get('status') in ('creator','administrator','member') or (member.get('status')=='restricted' and member.get('is_member') is True)
    return actor in config['approver_ids'] and member.get('status') in ('creator','administrator')
