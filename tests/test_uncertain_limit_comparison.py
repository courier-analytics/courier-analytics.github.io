import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from check_uncertain_attendance_limits import comparison
class Compare(unittest.TestCase):
 def test_match_does_not_claim_write_success_or_authorize_retry(self):
  self.assertEqual(comparison(4,5,4),'matches_target_but_write_attribution_not_proven')
  self.assertEqual(comparison(5,5,4),'matches_previous_limit_no_retry_authorized')
  self.assertEqual(comparison(7,5,4),'different_limit_requires_review')
