"""Explicitly reissue one pending proposal; never execute a 1C write."""
import argparse,fcntl,json,os,secrets,sqlite3
from datetime import datetime
from pathlib import Path
from attendance_cases import ROOT,connect,get
from attendance_bot import notify
from late_bot_group import load_token
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--date',required=True);parser.add_argument('--shop',type=int,required=True);parser.add_argument('--name',required=True);args=parser.parse_args()
 os.umask(0o077)
 with (ROOT/'bot.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  with connect() as db:
   rows=db.execute("SELECT id FROM cases WHERE json_extract(payload,'$.date')=? AND json_extract(payload,'$.shop_id')=? AND json_extract(payload,'$.name')=?",(args.date,args.shop,args.name)).fetchall()
   if len(rows)!=1:raise SystemExit('Expected exactly one matching case; nothing sent')
   case=get(db,rows[0]['id']);p=case['payload']
   if case['state']!='pending_review' or case['actor'] is not None or case['current_limit'] is None or case['target_limit'] is None:raise SystemExit('Not an unprocessed verified proposal; nothing sent')
   if db.execute('SELECT 1 FROM ledger WHERE day=? AND courier=?',(p['date'],p['courier_id'])).fetchone():raise SystemExit('Write ledger exists; nothing sent')
   with sqlite3.connect(ROOT/('before-resend-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')) as backup:db.backup(backup)
   db.execute("UPDATE cases SET state='ready',notified=0,nonce=? WHERE id=?",(secrets.token_hex(4),case['id']));db.commit()
   config=json.loads(Path('/etc/superset-telegram/late-group.json').read_text())
   notify(db,config,load_token(),only_id=case['id'])
   result=get(db,case['id'])
   print('Resent proposal; state:',result['state'],'message:',result['message_id'],'group:',result['message_chat_id'])
