"""Bind future DS 7745 notices to the explicitly requested group."""
import json,os,sqlite3
from pathlib import Path
from datetime import datetime
from late_bot_group import load_token,api
from prepare_openvpn import private_write
TARGET=-1004365044892
if __name__=='__main__':
 os.umask(0o077)
 path=Path('/etc/superset-telegram/late-group.json');config=json.loads(path.read_text());token=load_token()
 me=api(token,'getMe');chat=api(token,'getChat',{'chat_id':TARGET})
 if chat.get('id')!=TARGET or chat.get('type') not in ('group','supergroup'):raise ValueError('Group identity mismatch')
 member=api(token,'getChatMember',{'chat_id':TARGET,'user_id':me['id']})
 if member.get('status') not in ('administrator','creator'):raise ValueError('Bot must be an administrator in the selected group')
 reviewers=[]
 for identity in config['approver_ids']:
  try:member=api(token,'getChatMember',{'chat_id':TARGET,'user_id':identity})
  except RuntimeError:continue
  if member.get('status') in ('administrator','creator') and not member.get('user',{}).get('is_bot'):reviewers.append(identity)
 if not reviewers:raise ValueError('At least one existing authorized reviewer must be admin in the new group')
 backup=path.with_name('late-group.backup-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json');private_write(backup,path.read_text())
 config.setdefault('shop_routes',{})['7745']=TARGET
 private_write(path,json.dumps(config,ensure_ascii=False,indent=2))
 print('DS 7745 route saved:',chat.get('title'),TARGET,'authorized reviewers available:',len(reviewers))
 print('Existing messages retain their original group; future proposals use the new group.')
