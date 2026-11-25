"""Enable explicitly requested human group member review for DS 7745 only."""
import json
from pathlib import Path
from datetime import datetime
from late_bot_group import load_token,api
from prepare_openvpn import private_write
if __name__=='__main__':
 path=Path('/etc/superset-telegram/late-group.json');config=json.loads(path.read_text())
 chat=config.get('shop_routes',{}).get('7745')
 if chat!=-1004365044892:raise ValueError('DS 7745 group binding not verified')
 token=load_token();me=api(token,'getMe')
 if api(token,'getChatMember',{'chat_id':chat,'user_id':me['id']}).get('status')!='administrator':raise ValueError('Bot admin rights required to verify membership')
 private_write(path.with_name('late-group.before-member-review-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json'),path.read_text())
 config['member_approval_shops']=sorted(set(config.get('member_approval_shops',[]))|{7745})
 private_write(path,json.dumps(config,ensure_ascii=False,indent=2))
 print('DS 7745: any current human group member may Apply or Skip; other groups unchanged. Configuration reloads automatically; no restart required.')
