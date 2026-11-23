import sys,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from matryoshka_pools import label
class Pools(unittest.TestCase):
 def test_verified_zero_is_distinct_from_missing(self):
  now=datetime.now(timezone.utc)
  self.assertIn('Пул: 0',label('1',now,{'1':{'verified':True,'limit':0,'observed_at':now.isoformat()}}))
  self.assertIn('нет подтверждённых',label('2',now,{}))
 def test_stale_and_unverified_cannot_appear_current(self):
  now=datetime.now(timezone.utc);row={'verified':True,'limit':5,'observed_at':(now-timedelta(hours=1)).isoformat()}
  self.assertIn('устарело',label('1',now,{'1':row}))
  row['verified']=False
  self.assertIn('нет подтверждённых',label('1',now,{'1':row}))
if __name__=='__main__':unittest.main()
