import sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from onec_approved_measure import wait_for_persisted_limit
class Readback(unittest.TestCase):
 def test_waits_for_numeric_fields_and_two_stable_target_reads(self):
  page=Mock()
  with patch('onec_approved_measure.card',side_effect=[ValueError('not rendered'),('form1_',5,'10'),('form1_',4,'10'),('form1_',4,'10')]) as read:
   self.assertEqual(wait_for_persisted_limit(page,'123','Test Name',4,'10'),4)
   self.assertEqual(read.call_count,4)
   page.locator.assert_not_called()
 def test_transient_target_and_wrong_unrelated_field_never_confirm(self):
  page=Mock()
  with patch('onec_approved_measure.card',side_effect=[('form1_',4,'10'),('form1_',4,'11'),('form1_',5,'10')]):
   with self.assertRaises(ValueError):wait_for_persisted_limit(page,'123','Test Name',4,'10',attempts=3)
   page.locator.assert_not_called()
 def test_stable_wrong_value_does_not_trigger_another_save(self):
  page=Mock()
  with patch('onec_approved_measure.card',return_value=('form1_',5,'10')):
   with self.assertRaises(ValueError):wait_for_persisted_limit(page,'123','Test Name',4,'10',attempts=3)
   self.assertEqual(page.wait_for_timeout.call_count,2)
   page.locator.assert_not_called()
