import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from check_uncertain_attendance_limits import comparison
class Compare(unittest.TestCase):
 def test_match_does_not_claim_write_success_or_authorize_retry(self):
  self.assertEqual(comparison(4,5,4),'matches_target_but_write_attribution_not_proven')
  self.assertEqual(comparison(5,5,4),'matches_previous_limit_no_retry_authorized')
  self.assertEqual(comparison(7,5,4),'different_limit_requires_review')

class AccountWait(unittest.TestCase):
 def test_waits_until_current_owner_releases(self):
  from unittest.mock import patch,Mock
  from check_uncertain_attendance_limits import wait_for_account
  with patch('check_uncertain_attendance_limits.fcntl.flock',side_effect=[BlockingIOError, None]),patch('check_uncertain_attendance_limits.time.monotonic',side_effect=[0,1]),patch('check_uncertain_attendance_limits.time.sleep'):
   self.assertTrue(wait_for_account(Mock(),10))
 def test_timeout_never_forces_entry(self):
  from unittest.mock import patch,Mock
  from check_uncertain_attendance_limits import wait_for_account
  with patch('check_uncertain_attendance_limits.fcntl.flock',side_effect=BlockingIOError),patch('check_uncertain_attendance_limits.time.monotonic',side_effect=[0,10]),patch('check_uncertain_attendance_limits.time.sleep') as sleep:
   self.assertFalse(wait_for_account(Mock(),10));sleep.assert_not_called()
