import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from measure_courier_performance import analyze,statistics
class Timing(unittest.TestCase):
 def test_cross_transition_cycle_is_not_misrepresented_as_speedup(self):
  data=analyze([(1,'Starting job'),(9,'Finished job'),(11,'Starting job'),(20,'Finished job'),(21,'Starting job'),(29,'Finished job')],vpn=10,secondary=15)
  self.assertEqual(data['before_persistent_vpn']['completed_service_cycles']['mean_seconds'],8)
  self.assertEqual(data['after_second_account']['completed_service_cycles']['count'],1)
  self.assertEqual(data['after_second_account']['log_signals']['transition_cycle_excluded'],1)
 def test_failed_cycle_is_not_successful_duration(self):
  data=analyze([(1,'Starting job'),(3,'Failed with result exit-code'),(7,'Finished job')])
  self.assertEqual(data['before_persistent_vpn']['completed_service_cycles']['count'],0)
 def test_empty_sample_does_not_invent_latency(self):
  self.assertIsNone(statistics([])['mean_seconds'])
