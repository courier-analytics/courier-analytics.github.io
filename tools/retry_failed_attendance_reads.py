"""Explicit operator cleanup: delete failed-read notices and retry read-only cases."""
import fcntl,json,os,secrets,sqlite3
from datetime import datetime
from attendance_cases import connect,ROOT
from attendance_review import TZ
from late_bot_group import api,load_token
from prepare_openvpn import private_write
from pathlib import Path

def eligible(db,day):
 return db.execute("SELECT * FROM cases WHERE state IN ('held','pending_review') AND target_limit IS NULL AND result='limit_read_failed' AND json_extract(payload,'$.date')=? AND NOT EXISTS (SELECT 1 FROM ledger WHERE case_id=cases.id OR (day=json_extract(cases.payload,'$.date') AND courier=CAST(json_extract(cases.payload,'$.courier_id') AS TEXT)))",(day,)).fetchall()

def reset(db,identity):
 db.execute("UPDATE cases SET state='need_limit',current_limit=NULL,target_limit=NULL,observed=NULL,message_id=NULL,actor=NULL,result=NULL,notified=0,read_attempts=0,next_attempt=0,nonce=? WHERE id=? AND state IN ('held','pending_review') AND target_limit IS NULL AND result='limit_read_failed'",(secrets.token_hex(4),identity));db.commit()

def main():
 os.umask(0o077)
 config=json.loads(Path('/etc/superset-telegram/late-group.json').read_text())
 if config['chat_id']!=-1004439978802:raise ValueError('Unexpected group')
 token=load_token();day=datetime.now(TZ).date().isoformat()
 with (ROOT/'bot.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  with connect() as db:
   folder=ROOT/('retry-backup-'+datetime.now(TZ).strftime('%Y%m%d-%H%M%S'));folder.mkdir(mode=0o700)
   with sqlite3.connect(folder/'cases.sqlite3') as backup:db.backup(backup)
   rows=eligible(db,day);done=0
   for row in rows:
    private_write(folder/(row['id']+'.json'),json.dumps(dict(row),ensure_ascii=False))
    if row['message_id'] is not None:
     # Persist deletion intent; unknown outcomes require inspection, not a new send.
     try:api(token,'deleteMessage',{'chat_id':config['chat_id'],'message_id':row['message_id']})
     except Exception:
      print('Notice deletion not confirmed; case unchanged:',row['id'],flush=True);continue
    reset(db,row['id']);done+=1
   print('Failed-read notices removed and read-only cases queued:',done,'of',len(rows),flush=True)
if __name__=='__main__':main()
