"""Matryoshka command handler sharing the attendance Telegram receiver.

Rendering and command semantics preserved from the supplied deployed handler.
"""
import json,sqlite3
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from matryoshka_command_report import command,render
from late_bot_group import api
ROOT=Path('/opt/courier-analytics/private')

class Handler:
    def __init__(self,token,username):
        self.token=token;self.username=username
        config=Path('/etc/superset-telegram/test-group.json')
        if config.stat().st_mode & 0o077:raise ValueError('Matryoshka configuration not private')
        self.chat=json.loads(config.read_text())['chat_id']
        if self.chat!=-1004427986473:raise ValueError('Unexpected Matryoshka group')
        self.db=sqlite3.connect(ROOT/'matryoshka-commands.sqlite3')
        self.db.execute('CREATE TABLE IF NOT EXISTS updates (id INTEGER PRIMARY KEY,status TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY,value TEXT NOT NULL)');self.db.commit()
    def handle(self,update):
        token,chat,username,db=self.token,self.chat,self.username,self.db
        uid=update['update_id'];msg=update.get('message',{})
        if msg.get('chat',{}).get('id')==chat and not msg.get('from',{}).get('is_bot'):
            try:number=command(msg.get('text',''),username)
            except ValueError:number=None;pages=['Использование: /matreshka [номер] или /matreshka_idle [номер]']
            else:pages=None
            if number is not None or pages:
                # Ignore delayed commands from before this receiver's installation.
                installed=Path('/opt/courier-matryoshka-commands/installed-at').stat().st_mtime
                if msg.get('date',0)>=installed:
                    cursor=db.execute("INSERT OR IGNORE INTO updates(id,status) VALUES (?, 'inflight')",(uid,));db.commit()
                    if cursor.rowcount:
                        if pages is None:
                            try:
                                snapshot=json.loads((ROOT/'matryoshka-monitor.json').read_text())
                                roster=Path('/opt/courier-contacts/connected/all.json')
                                rosters=json.loads(roster.read_text()) if roster.exists() else {}
                                pool_path=ROOT/'matryoshka-pools.json'
                                try:pools=json.loads(pool_path.read_text())
                                except (OSError,ValueError):pools={}
                                pages=render(snapshot,number,datetime.now(ZoneInfo('Europe/Moscow')),rosters,pools=pools,idle_days=3 if msg.get('text','').split()[0].split('@')[0].lower()=='/matreshka_idle' else None)
                            except Exception:pages=['Список Матрёшки пока недоступен: источник не подтверждён или данные некорректны.']
                        try:
                            for page in pages:
                                api(token,'sendMessage',{'chat_id':chat,'text':page,'reply_parameters':{'message_id':msg['message_id'],'allow_sending_without_reply':True}})
                        except Exception:
                            db.execute("UPDATE updates SET status='uncertain' WHERE id=?",(uid,));db.commit()
                            print('Command reply uncertain; automatic duplicate suppressed',flush=True)
                        else:
                            db.execute("UPDATE updates SET status='sent' WHERE id=?",(uid,));db.commit()
                            print('MATRYOSHKA COMMAND REPLIED',flush=True)
        return update.get("message",{}).get("chat",{}).get("id")==chat
