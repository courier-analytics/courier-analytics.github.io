import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from services_pilot import chart_data
class PilotTests(unittest.TestCase):
 def test_async_job_waits_for_cached_result(self):
  answer={'result':[{'status':'success','data':[{'shopno':9107}]}]}
  with patch('services_pilot.api',side_effect=[(202,{'result':{'cache_key':'abc123'}}),(400,{}),(200,answer)]) as call,patch('services_pilot.time.sleep'):
   self.assertEqual(chart_data(None,'TOKEN',{}),(200,answer))
   self.assertEqual(call.call_args.args[1],'/api/v1/chart/data/abc123')
 def test_job_key_cannot_change_request_path(self):
  with patch('services_pilot.api',return_value=(202,{'result':{'cache_key':'../../secret'}})) as call:
   self.assertEqual(chart_data(None,'TOKEN',{})[0],202)
   self.assertEqual(call.call_count,1)
