"""Route each proposal and its outcome to the same bound Telegram group."""
def case_config(config,case):
    bound=case.get('message_chat_id')
    if bound is None:
        bound=config['chat_id'] if case.get('message_id') else config.get('shop_routes',{}).get(str(case['payload']['shop_id']),config['chat_id'])
    return {**config,'chat_id':bound}
