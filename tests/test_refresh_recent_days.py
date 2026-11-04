import sys,unittest
from pathlib import Path
from datetime import date
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from refresh_recent_days import run

class RecentDayRefreshTests(unittest.TestCase):
 def test_yesterday_failure_does_not_prevent_today_or_claim_success(self):
  report={'report':{'summaries':[{'shop_id':7745,'metrics':{}}]}}
  with patch('refresh_recent_days.refresh',side_effect=[ValueError('private source details'),report]) as refresh:
   rows=run(date(2026,11,4),'secret','proxy',Path('/tmp/test'),Path('/tmp/feed'))
  self.assertEqual([c.args[0] for c in refresh.call_args_list],['2026-11-03','2026-11-04'])
  self.assertEqual([r['ok'] for r in rows],[False,True])
  self.assertNotIn('private source details',str(rows));self.assertNotIn('secret',str(rows))
 def test_successful_historical_refresh_is_retained_when_current_source_fails(self):
  report={'report':{'summaries':[{'shop_id':7745,'metrics':{'planned_completion':{'value':None,'reason':'shift_end_or_final_status_missing'}}}]}}
  with patch('refresh_recent_days.refresh',side_effect=[report,OSError('network')]):
   rows=run(date(2026,11,4),'secret','proxy',Path('/tmp/test'),Path('/tmp/feed'))
  self.assertTrue(rows[0]['ok']);self.assertFalse(rows[1]['ok'])
  self.assertEqual(rows[0]['unavailable']['planned_completion'],'shift_end_or_final_status_missing')
