import sys,unittest,tempfile,json,sqlite3,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from matryoshka_command_handler import Handler
from matryoshka_command_report import command
class SharedCommands(unittest.TestCase):
 def test_commands_preserved(self):
  self.assertEqual(command('/matreshka 9107','bot'),'9107')
  self.assertEqual(command('/matreshka_idle@bot 8889','bot'),'8889')
  self.assertIsNone(command('/matreshka@other','bot'))
 def test_group_routing_and_duplicate_suppression(self):
  handler=Handler.__new__(Handler);handler.token='fixture';handler.username='bot';handler.chat=-1004427986473
  handler.db=sqlite3.connect(':memory:');handler.db.execute('CREATE TABLE updates(id INTEGER PRIMARY KEY,status TEXT)')
  msg={'update_id':3,'message':{'chat':{'id':handler.chat},'from':{'is_bot':False},'text':'/matreshka','date':time.time()+5,'message_id':8}}
  with tempfile.TemporaryDirectory() as directory:
   installed=Path(directory)/'installed-at';installed.touch()
   original_stat=Path.stat
   def stat(path,*args,**kwargs):return original_stat(installed if str(path)=='/opt/courier-matryoshka-commands/installed-at' else path,*args,**kwargs)
   with patch('matryoshka_command_handler.Path.stat',stat),patch('matryoshka_command_handler.api') as api:
    self.assertTrue(handler.handle(msg));handler.handle(msg);self.assertEqual(api.call_count,1)
    self.assertFalse(handler.handle({'update_id':4,'message':{'chat':{'id':-1},'text':'/matreshka'}}))
    self.assertFalse(handler.handle({'update_id':5,'callback_query':{'data':'att:a:x'}}))
  handler.db.close()
if __name__=='__main__':unittest.main()
