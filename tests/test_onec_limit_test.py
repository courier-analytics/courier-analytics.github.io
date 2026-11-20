import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from onec_limit_test import integer,decision,BEFORE,AFTER
class LimitTestGuards(unittest.TestCase):
 def test_only_fixed_transition_allowed(self):
  self.assertEqual(decision(BEFORE,False),'write_once')
  self.assertEqual(decision(AFTER,False),'verify_only')
  self.assertEqual(decision(AFTER,True),'verify_only')
  for value in (7395,7392,0):
   with self.assertRaises(ValueError):decision(value,False)
 def test_uncertain_prior_attempt_not_retried(self):
  with self.assertRaises(ValueError):decision(BEFORE,True)
 def test_count_not_confused_with_taking_time(self):
  self.assertEqual(integer('7394 '),7394)
  for value in ('7,394','7.394','-1',''):
   with self.assertRaises(ValueError):integer(value)
if __name__=='__main__':unittest.main()
