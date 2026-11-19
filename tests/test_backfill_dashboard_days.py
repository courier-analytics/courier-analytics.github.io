import json,sys,tempfile,unittest
from pathlib import Path
from datetime import date,datetime
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from backfill_dashboard_days import run,window
class BackfillDaysTests(unittest.TestCase):
 def test_window_bounds(self):
  self.assertEqual(len(window(date(2026,11,17),date(2026,11,19))),3)
  with self.assertRaises(ValueError):window(date(2026,11,19),date(2026,11,17))
 def test_failed_run_resumes_completed_history_before_publication(self):
  with tempfile.TemporaryDirectory() as tmp:
   base=Path(tmp);(base/'current-site/data').mkdir(parents=True)
   session=base/'session.json';session.write_text(json.dumps({'token':'test'}))
   calls=[];publishes=[];fail=[True]
   def collect(day,token,proxy,private,feed,**kwargs):
    calls.append(day)
    if day=='2026-11-18' and fail[0]:raise RuntimeError('test interruption')
    row={'shop_id':9107,'date':day,'reported_at':day+'T12:00:00+03:00','metrics':{}}
    old=json.loads(feed.read_text()) if feed.exists() else {'records':[]}
    old['records']=[r for r in old['records'] if r['date']!=day]+[row];feed.write_text(json.dumps(old))
    return {'report':{'summaries':[row]}}
   kwargs=dict(shop=9107,first=date(2026,11,17),last=date(2026,11,19),base=base,session=session,collect=collect,publish=lambda f:publishes.append(f),now=datetime(2026,11,19,tzinfo=ZoneInfo('Europe/Moscow')))
   with self.assertRaises(RuntimeError):run(**kwargs)
   self.assertEqual(publishes,[])
   fail[0]=False;state=run(**kwargs)
   self.assertEqual(calls.count('2026-11-17'),1)
   self.assertTrue(state['published']);self.assertEqual(len(state['dates']),3)
   self.assertEqual(len(publishes),1)
if __name__=='__main__':unittest.main()
