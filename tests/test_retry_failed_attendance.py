import sys,unittest,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from attendance_cases import connect
from retry_failed_attendance_reads import eligible,reset
class Retry(unittest.TestCase):
 def test_only_failed_reads_without_any_write_ledger_are_selected(self):
  with tempfile.TemporaryDirectory() as directory:
   db=connect(Path(directory)/'cases.db')
   for i,state in enumerate(('pending_review','applied','skipped','held')):
    db.execute('INSERT INTO cases(id,event,payload,state,result,read_attempts) VALUES (?,?,?,?,?,3)',(str(i),str(i),json.dumps({'date':'2026-11-23','courier_id':str(i)}),state,'limit_read_failed'))
   db.execute("INSERT INTO ledger VALUES ('2026-11-23','3','uncertain','3')");db.commit()
   self.assertEqual([r['id'] for r in eligible(db,'2026-11-23')],['0'])
   reset(db,'0')
   row=db.execute("SELECT state,read_attempts,actor,message_id FROM cases WHERE id='0'").fetchone()
   self.assertEqual(tuple(row),('need_limit',0,None,None));db.close()
if __name__=='__main__':unittest.main()
