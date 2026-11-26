"""Enable human member decisions for DS9107 in its existing attendance group."""
import json
from pathlib import Path
from datetime import datetime
from late_bot_group import load_token,api
from prepare_openvpn import private_write

CHAT=-1004439978802

def enabled_config(config):
    if config.get('chat_id')!=CHAT or config.get('shop_routes',{}).get('9107',CHAT)!=CHAT:
        raise ValueError('Existing DS9107 group binding not verified')
    return {**config,'shop_routes':{**config.get('shop_routes',{}),'9107':CHAT},
            'member_approval_shops':sorted(set(config.get('member_approval_shops',[]))|{9107})}

if __name__=='__main__':
    path=Path('/etc/superset-telegram/late-group.json')
    original=path.read_text();config=json.loads(original)
    updated=enabled_config(config)
    token=load_token();me=api(token,'getMe')
    if me.get('id')!=config.get('bot_id'):raise ValueError('Configured bot identity mismatch')
    if api(token,'getChat',{'chat_id':CHAT}).get('id')!=CHAT:raise ValueError('Group not verified')
    if api(token,'getChatMember',{'chat_id':CHAT,'user_id':me['id']}).get('status')!='administrator':
        raise ValueError('Bot admin rights required to verify membership')
    if path.read_text()!=original:raise ValueError('Configuration changed during verification; retry')
    private_write(path.with_name('late-group.before-9107-member-review-'+datetime.now().strftime('%Y%m%d-%H%M%S%f')+'.json'),original)
    private_write(path,json.dumps(updated,ensure_ascii=False,indent=2))
    print('DS 9107: current human group members may Apply or Skip. Other shop policies preserved. No restart required.')
